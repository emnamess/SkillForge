"""Moteur de recommandation de certifications (IA).

Recommande à un apprenant les prochaines certifications à préparer, à partir :

1. de **ses infos** : compétences déjà validées et présentation de son profil (filtrage par contenu) ;
2. de **ce qu'ont fait les autres** : « ceux qui ont obtenu X ont aussi obtenu Y » (filtrage collaboratif).

Filtrage par contenu
    Chaque cours est décrit par un texte (titre + compétences + description). Le texte est transformé en
    vecteur TF-IDF : un mot pèse lourd s'il est fréquent dans ce cours et rare dans les autres. Le profil de
    l'apprenant est la moyenne des vecteurs de ses cours certifiés, enrichie par sa présentation. On
    recommande les cours dont le vecteur est le plus proche (similarité cosinus).

Filtrage collaboratif (item-item)
    Matrice apprenants × cours (1 = certifié). Deux cours sont proches s'ils sont souvent obtenus par les
    mêmes apprenants (similarité cosinus entre colonnes). Le score d'un cours candidat est sa similarité
    moyenne avec les cours déjà obtenus.

Hybride
    score = ALPHA × contenu + (1 − ALPHA) × collaboratif, chaque score étant ramené entre 0 et 1.
    Sans aucune donnée sur l'apprenant (démarrage à froid), on propose les cours les plus populaires.

Le modèle s'entraîne en quelques millisecondes : il est mis en cache et réentraîné seulement quand les
certificats changent. La qualité est mesurée par `evaluer()` (voir la page « Performance du modèle »).
"""

import logging
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from django.conf import settings
from sklearn.feature_extraction.text import TfidfVectorizer, strip_accents_unicode
from sklearn.metrics.pairwise import cosine_similarity

from .models import Certificat

logger = logging.getLogger(__name__)

NB_RECOMMANDATIONS = 3
POIDS_PROFIL = 0.5  # importance de la présentation de l'apprenant face à ses compétences validées
# Nouvel apprenant (aucune certification) : on mélange son profil et la popularité, car les débutants
# commencent souvent par les cours d'entrée (0,3 = meilleur résultat de evaluer_demarrage_a_froid())
POIDS_POPULARITE_NOUVEAU = 0.3

# Mots vides français : ignorés par TF-IDF (scikit-learn ne fournit qu'une liste anglaise)
MOTS_VIDES = sorted({strip_accents_unicode(mot) for mot in {
    "a", "au", "aux", "avec", "ce", "ces", "cet", "cette", "d", "dans", "de", "des", "du", "elle", "en", "et",
    "il", "ils", "j", "je", "l", "la", "le", "les", "leur", "lui", "m", "ma", "me", "mes", "mon", "ne", "nous",
    "on", "ou", "par", "pas", "pour", "qu", "que", "qui", "s", "sa", "se", "ses", "son", "sur", "t", "ta",
    "te", "tes", "ton", "tu", "un", "une", "vos", "votre", "vous", "y", "est", "sont", "suis", "être", "plus",
    "aussi", "très", "bien", "faire", "compte", "démonstration", "profil", "apprenant", "apprenante",
}})


def alpha_par_defaut():
    # 0,4 : meilleur compromis HitRate / MRR mesuré par comparer_alphas() sur les données de démo
    return getattr(settings, "RECOMMANDATION_ALPHA", 0.4)


# ---------- Données ----------

@dataclass
class Cours:
    cle: str                      # titre normalisé (casse et espaces ignorés)
    titre: str                    # titre affiché
    competences: list = field(default_factory=list)
    description: str = ""

    @property
    def texte(self):
        # Le titre est répété : il décrit le cours mieux qu'une compétence isolée
        return " ".join([self.titre, self.titre, " ".join(self.competences), self.description])


def construire_catalogue(certificats):
    """Catalogue des cours connus : module cours s'il existe, sinon les cours vus dans les certificats.

    Les compétences d'un cours sont l'union des compétences de ses certificats.
    """
    titres, competences = defaultdict(Counter), defaultdict(dict)
    for c in certificats:
        cle = Certificat.normaliser_titre(c.titre_cours)
        titres[cle][c.titre_cours] += 1
        for comp in c.liste_competences:
            competences[cle].setdefault(comp.casefold(), comp)

    catalogue = {
        cle: Cours(cle, compteur.most_common(1)[0][0], sorted(competences[cle].values(), key=str.casefold))
        for cle, compteur in titres.items()
    }
    for cle, titre, description in cours_du_module_cours():
        cours = catalogue.setdefault(cle, Cours(cle, titre))
        cours.description = description
    return catalogue


def cours_du_module_cours():
    """(clé, titre, description) des cours publiés par le module cours, quand il sera disponible."""
    from django.apps import apps
    try:
        modele = apps.get_model("courses", "Cours")
    except LookupError:
        return []
    noms = {f.name for f in modele._meta.get_fields()}
    if "titre" not in noms:
        return []
    champs = ["titre"] + (["description"] if "description" in noms else [])
    return [(Certificat.normaliser_titre(ligne["titre"]), ligne["titre"], ligne.get("description") or "")
            for ligne in modele.objects.values(*champs)]


# ---------- Modèle ----------

@dataclass
class Recommandation:
    titre: str
    score: float                  # pertinence entre 0 et 1
    raisons: list
    competences_nouvelles: list   # compétences du cours que l'apprenant n'a pas encore validées
    source: str                   # "hybride" ou "populaires"

    @property
    def niveau(self):
        """Libellé lisible : le score est un indice de similarité, pas une probabilité."""
        if self.source == "populaires":
            return "Populaire"
        # Seuils choisis pour répartir les suggestions des données de démo en trois tiers environ
        if self.score >= 0.55:
            return "Très pertinent"
        if self.score >= 0.35:
            return "Pertinent"
        return "À explorer"

    def en_dict(self):
        return {"titre": self.titre, "score": round(self.score, 3), "niveau": self.niveau,
                "raisons": self.raisons, "competences_nouvelles": self.competences_nouvelles,
                "source": self.source}


class ModeleRecommandation:
    """Modèle hybride entraîné sur une liste de couples (apprenant, cours certifié)."""

    def __init__(self, catalogue, certifications, alpha=None):
        self.catalogue = catalogue
        self.alpha = alpha_par_defaut() if alpha is None else alpha
        self.cles = sorted(catalogue)
        self.index = {cle: i for i, cle in enumerate(self.cles)}
        self.certifications = [(u, c) for u, c in certifications if c in self.index]
        debut = time.perf_counter()
        self._entrainer()
        self.duree_entrainement_ms = (time.perf_counter() - debut) * 1000

    def _entrainer(self):
        # 1. Contenu : un vecteur TF-IDF par cours
        self.vectoriseur = TfidfVectorizer(stop_words=MOTS_VIDES, strip_accents="unicode", ngram_range=(1, 2),
                                           sublinear_tf=True, token_pattern=r"(?u)\b\w\w+\b")
        try:
            self.vecteurs = self.vectoriseur.fit_transform([self.catalogue[c].texte for c in self.cles])
        except ValueError:  # catalogue vide, ou textes sans aucun mot utile : pas de filtrage par contenu
            self.vectoriseur = self.vecteurs = None

        # 2. Collaboratif : matrice apprenants × cours, puis similarité entre cours
        apprenants = sorted({u for u, _ in self.certifications})
        ligne = {u: i for i, u in enumerate(apprenants)}
        self.matrice = np.zeros((len(apprenants), len(self.cles)))
        for u, c in self.certifications:
            self.matrice[ligne[u], self.index[c]] = 1
        if len(apprenants):
            self.similarite_cours = cosine_similarity(self.matrice.T)
            np.fill_diagonal(self.similarite_cours, 0)
        else:
            self.similarite_cours = np.zeros((len(self.cles), len(self.cles)))
        self.popularite = self.matrice.sum(axis=0)
        self.nb_apprenants = len(apprenants)

    # -- Scores --

    @staticmethod
    def _normaliser(scores):
        maximum = scores.max() if scores.size else 0
        return scores / maximum if maximum > 0 else np.zeros_like(scores)

    def scores_contenu(self, deja, profil=""):
        if self.vecteurs is None:
            return np.zeros(len(self.cles))
        indices = [self.index[c] for c in deja if c in self.index]
        vecteur = None
        if indices:
            vecteur = np.asarray(self.vecteurs[indices].mean(axis=0))
        if profil.strip():
            vecteur_profil = self.vectoriseur.transform([profil]).toarray()
            if vecteur_profil.any():
                vecteur = POIDS_PROFIL * vecteur_profil if vecteur is None else vecteur + POIDS_PROFIL * vecteur_profil
        if vecteur is None:
            return np.zeros(len(self.cles))
        return self._normaliser(cosine_similarity(vecteur, self.vecteurs).ravel())

    def scores_collaboratifs(self, deja):
        indices = [self.index[c] for c in deja if c in self.index]
        if not indices or not self.nb_apprenants:
            return np.zeros(len(self.cles))
        return self._normaliser(self.similarite_cours[indices].mean(axis=0))

    def scores(self, deja, profil="", methode="hybride"):
        if methode == "populaires":
            return self._normaliser(self.popularite.astype(float))
        contenu = self.scores_contenu(deja, profil) if methode != "collaboratif" else 0
        collab = self.scores_collaboratifs(deja) if methode != "contenu" else 0
        alpha = {"contenu": 1.0, "collaboratif": 0.0}.get(methode, self.alpha)
        scores = alpha * contenu + (1 - alpha) * collab + np.zeros(len(self.cles))
        if methode == "hybride" and not any(c in self.index for c in deja) and scores.any():
            populaires = self._normaliser(self.popularite.astype(float))
            scores = (1 - POIDS_POPULARITE_NOUVEAU) * self._normaliser(scores) + POIDS_POPULARITE_NOUVEAU * populaires
        return scores

    def classement(self, deja, profil="", methode="hybride"):
        """Clés des cours candidats, de la plus à la moins pertinente (cours déjà obtenus exclus)."""
        scores = self.scores(deja, profil, methode)
        popularite = self._normaliser(self.popularite.astype(float))
        exclus = set(deja)
        candidats = [(scores[i], popularite[i], cle) for i, cle in enumerate(self.cles) if cle not in exclus]
        # À score égal, le cours le plus populaire passe devant (puis l'ordre alphabétique : résultat stable)
        candidats.sort(key=lambda t: (-t[0], -t[1], t[2]))
        return [(cle, score) for score, _, cle in candidats]

    # -- Recommandations expliquées --

    def recommander(self, deja, profil="", k=NB_RECOMMANDATIONS):
        classement = self.classement(deja, profil)
        source = "hybride"
        if not classement or classement[0][1] <= 0:
            # Démarrage à froid : aucune compétence ni présentation exploitable
            classement = self.classement(deja, profil, methode="populaires")
            source = "populaires"

        # Moins de k cours pertinents : on complète avec les plus populaires
        choisis = [(cle, score, source) for cle, score in classement if score > 0][:k]
        if len(choisis) < k:
            deja_choisis = {cle for cle, _, _ in choisis}
            for cle, score in self.classement(deja, profil, methode="populaires"):
                if len(choisis) == k:
                    break
                if cle not in deja_choisis:
                    choisis.append((cle, score, "populaires"))

        mes_competences = {comp.casefold() for c in deja if c in self.catalogue
                           for comp in self.catalogue[c].competences}
        resultats = []
        for cle, score, origine in choisis:
            cours = self.catalogue[cle]
            resultats.append(Recommandation(
                titre=cours.titre,
                score=float(max(0.0, min(1.0, score))),
                raisons=self.raisons(cle, deja, profil, origine),
                competences_nouvelles=[c for c in cours.competences if c.casefold() not in mes_competences],
                source=origine,
            ))
        return resultats

    def raisons(self, cle, deja, profil, source):
        cours = self.catalogue[cle]
        raisons = []
        if source == "populaires":
            n = int(self.popularite[self.index[cle]])
            return [f"Parmi les certifications les plus obtenues ({n} apprenant{'s' if n > 1 else ''})."]

        # Compétences en commun avec un cours déjà obtenu
        competences_cours = {c.casefold(): c for c in cours.competences}
        meilleur = None
        for c in deja:
            if c not in self.catalogue:
                continue
            communes = [competences_cours[x.casefold()] for x in self.catalogue[c].competences
                        if x.casefold() in competences_cours]
            if communes and (meilleur is None or len(communes) > len(meilleur[1])):
                meilleur = (self.catalogue[c].titre, communes)
        if meilleur:
            raisons.append(f"Compétences en commun avec « {meilleur[0]} » : {', '.join(meilleur[1])}.")

        # Parcours des autres apprenants
        j = self.index[cle]
        meilleur_taux = None
        for c in deja:
            if c not in self.index:
                continue
            i = self.index[c]
            obtenus_i = self.matrice[:, i].sum()
            if obtenus_i:
                taux = (self.matrice[:, i] * self.matrice[:, j]).sum() / obtenus_i
                if taux > 0 and (meilleur_taux is None or taux > meilleur_taux[1]):
                    meilleur_taux = (self.catalogue[c].titre, taux)
        if meilleur_taux:
            raisons.append(f"{round(100 * meilleur_taux[1])} % des apprenants certifiés en « {meilleur_taux[0]} » "
                           f"ont aussi obtenu cette certification.")

        # Mots de la présentation qui correspondent au cours
        if profil.strip() and self.vectoriseur is not None:
            analyse = self.vectoriseur.build_analyzer()
            mots_cours = set(analyse(cours.texte))
            communs = [m for m in dict.fromkeys(analyse(profil)) if " " not in m and m in mots_cours]
            if communs:
                raisons.append(f"Correspond à votre présentation : {', '.join(communs[:3])}.")

        return raisons or ["Proche des certifications que vous avez déjà obtenues."]


# ---------- Utilisation dans l'application (avec cache) ----------

_cache = {"version": None, "modele": None}


def _certificats_valides():
    return list(Certificat.objects.filter(statut=Certificat.Statut.VALIDE)
                .only("apprenant_id", "titre_cours", "competences"))


def modele_courant():
    """Modèle entraîné sur tous les certificats valides ; réentraîné seulement si les données ont changé."""
    certificats = _certificats_valides()
    version = (len(certificats), hash(frozenset((c.apprenant_id, c.titre_cours, c.competences) for c in certificats)),
               alpha_par_defaut())
    if _cache["version"] != version:
        catalogue = construire_catalogue(certificats)
        couples = [(c.apprenant_id, Certificat.normaliser_titre(c.titre_cours)) for c in certificats]
        _cache["modele"] = ModeleRecommandation(catalogue, couples)
        _cache["version"] = version
    return _cache["modele"]


def profil_texte(user):
    return " ".join(filter(None, [user.specialite, user.bio]))


def recommandations_pour(user, k=NB_RECOMMANDATIONS):
    """Renvoie (liste de Recommandation, durée en ms)."""
    debut = time.perf_counter()
    modele = modele_courant()
    deja = {Certificat.normaliser_titre(t) for t in Certificat.objects.filter(
        apprenant=user, statut=Certificat.Statut.VALIDE).values_list("titre_cours", flat=True)}
    resultats = modele.recommander(deja, profil_texte(user), k) if modele.cles else []
    return resultats, (time.perf_counter() - debut) * 1000


# ---------- Évaluation hors ligne ----------

METHODES = [
    ("populaires", "Les plus populaires (référence naïve)"),
    ("contenu", "Filtrage par contenu (TF-IDF)"),
    ("collaboratif", "Filtrage collaboratif (item-item)"),
    ("hybride", "Hybride (modèle utilisé)"),
]


def evaluer(certificats=None, profils=None, k=NB_RECOMMANDATIONS, repetitions=5, alpha=None):
    """Protocole « leave-one-out » : pour chaque apprenant ayant au moins 2 certifications, on en cache une
    au hasard, on entraîne le modèle sur tout le reste, et on regarde si la certification cachée apparaît
    dans les k premières recommandations. L'expérience est répétée avec `repetitions` tirages différents
    et les métriques sont moyennées (résultat plus fiable avec peu d'apprenants).

    Métriques (moyennes sur les apprenants testés) :
      - HitRate@k = Recall@k : part des certifications cachées retrouvées dans le top k ;
      - Precision@k : part des k recommandations qui étaient la bonne (au plus 1/k ici) ;
      - MRR : moyenne de 1/rang de la certification cachée (1 = toujours en tête) ;
      - NDCG@k : récompense une bonne réponse d'autant plus qu'elle est haut placée.
    """
    if certificats is None:
        certificats = _certificats_valides()
    if profils is None:
        from django.contrib.auth import get_user_model
        ids = {c.apprenant_id for c in certificats}
        profils = {u.pk: profil_texte(u) for u in get_user_model().objects.filter(pk__in=ids)}

    par_apprenant = defaultdict(list)
    for c in certificats:
        cle = Certificat.normaliser_titre(c.titre_cours)
        if cle not in par_apprenant[c.apprenant_id]:
            par_apprenant[c.apprenant_id].append(cle)
    catalogue = construire_catalogue(certificats)
    testables = [u for u in sorted(par_apprenant) if len(par_apprenant[u]) >= 2]

    resultat = {
        "k": k, "nb_apprenants_testes": len(testables), "nb_certificats": len(certificats),
        "nb_cours": len(catalogue), "nb_apprenants": len(par_apprenant), "repetitions": repetitions,
        "alpha": alpha_par_defaut() if alpha is None else alpha, "duree_entrainement_ms": 0.0, "methodes": [],
    }
    if not testables:
        return resultat

    cumul = {m: defaultdict(list) for m, _ in METHODES}
    for graine in range(repetitions):
        hasard = random.Random(graine)
        caches = {u: hasard.choice(sorted(par_apprenant[u])) for u in testables}
        entrainement = [(u, c) for u, cours in par_apprenant.items() for c in cours if c != caches.get(u)]
        modele = ModeleRecommandation(catalogue, entrainement, alpha=alpha)
        resultat["duree_entrainement_ms"] += modele.duree_entrainement_ms / repetitions

        for methode, _ in METHODES:
            hits = rr = ndcg = 0.0
            debut = time.perf_counter()
            for u, cible in caches.items():
                deja = [c for c in par_apprenant[u] if c != cible]
                rangs = [cle for cle, _ in modele.classement(deja, profils.get(u, ""), methode)]
                rang = rangs.index(cible) + 1 if cible in rangs else None
                if rang:
                    rr += 1 / rang
                    if rang <= k:
                        hits += 1
                        ndcg += 1 / math.log2(rang + 1)
            n = len(caches)
            mesures = cumul[methode]
            mesures["hit_rate"].append(hits / n)
            mesures["precision"].append(hits / (n * k))
            mesures["mrr"].append(rr / n)
            mesures["ndcg"].append(ndcg / n)
            mesures["latence_ms"].append((time.perf_counter() - debut) * 1000 / n)

    for methode, libelle in METHODES:
        mesures = {nom: float(np.mean(valeurs)) for nom, valeurs in cumul[methode].items()}
        mesures["hit_rate_ecart"] = float(np.std(cumul[methode]["hit_rate"]))
        resultat["methodes"].append({"methode": methode, "libelle": libelle, **mesures})
    reference = resultat["methodes"][0]["hit_rate"]
    for m in resultat["methodes"]:
        m["gain"] = (m["hit_rate"] - reference) / reference if reference else None
    return resultat


def evaluer_demarrage_a_froid(certificats=None, k=NB_RECOMMANDATIONS):
    """Nouvel apprenant : aucune certification, seulement sa présentation.

    Pour chaque apprenant qui a rempli sa présentation, on fait comme s'il n'avait encore rien obtenu et on
    compare le top k aux certifications qu'il a réellement passées : Precision@k (part des k suggestions
    qu'il a vraiment obtenues) et Recall@k (part de ses certifications retrouvées). Le filtrage
    collaboratif seul ne peut rien proposer ici : c'est la partie « contenu » du modèle hybride qui travaille.
    """
    from django.contrib.auth import get_user_model
    if certificats is None:
        certificats = _certificats_valides()
    par_apprenant = defaultdict(set)
    for c in certificats:
        par_apprenant[c.apprenant_id].add(Certificat.normaliser_titre(c.titre_cours))
    profils = {u.pk: profil_texte(u) for u in get_user_model().objects.filter(pk__in=par_apprenant)}
    testes = [u for u in par_apprenant if profils.get(u, "").strip()]
    catalogue = construire_catalogue(certificats)
    resultat = {"k": k, "nb_apprenants_testes": len(testes), "methodes": []}
    if not testes:
        return resultat
    for methode, libelle in (("populaires", "Les plus populaires"), ("hybride", "Hybride (contenu du profil)")):
        precision = rappel = 0.0
        for u in testes:
            # Le modèle est entraîné sans les certificats de cet apprenant
            autres = [(a, c) for a, cours in par_apprenant.items() if a != u for c in cours]
            modele = ModeleRecommandation(catalogue, autres)
            justes = len(par_apprenant[u] & {cle for cle, _ in modele.classement([], profils[u], methode)[:k]})
            precision += justes / k
            rappel += justes / min(k, len(par_apprenant[u]))
        n = len(testes)
        resultat["methodes"].append({"methode": methode, "libelle": libelle,
                                     "precision": precision / n, "rappel": rappel / n})
    return resultat


def comparer_alphas(valeurs=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0), **kwargs):
    """HitRate@k et MRR du modèle hybride selon le poids ALPHA donné au contenu."""
    certificats = _certificats_valides()
    lignes = []
    for a in valeurs:
        r = evaluer(certificats=certificats, alpha=a, **kwargs)
        hybride = next((m for m in r["methodes"] if m["methode"] == "hybride"), None)
        if hybride:
            lignes.append({"alpha": a, "hit_rate": hybride["hit_rate"], "mrr": hybride["mrr"]})
    return lignes
