"""Logique métier de l'Espace Carrière : les vues restent fines.

    from apps.careers import services

    resultat = services.calculer_score([(competence_id, niveau_requis, obligatoire), ...],
                                       {competence_id: niveau_apprenant})
    resultat.score                    # 0 à 100, ou None si l'offre n'a aucune compétence requise
    resultat.obligatoires_manquantes  # vrai si une compétence obligatoire manque totalement

    services.scores_offres(apprenant, offres)         # tous les scores, sans requêtes N+1
    services.ecart_competences(offre, apprenant)      # ce qu'il manque pour cette offre
    services.postuler(offre, apprenant, lettre)       # lève ValidationError si impossible
    services.changer_statut(candidature, auteur, Candidature.Statut.EN_EXAMEN)
"""

import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import (Avg, Case, Count, DurationField, ExpressionWrapper, F, IntegerField, OuterRef,
                              Q, Subquery, Value, When, prefetch_related_objects)
from django.db.models.functions import Coalesce
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from . import integrations
from .models import (Candidature, Competence, CompetenceApprenant, CompetenceRequise, HistoriqueCandidature,
                     Niveau, Offre, ProfilCarriere, ProfilEntreprise, SignalementOffre, TypeContrat)

logger = logging.getLogger(__name__)

CV_TAILLE_MAX = 5 * 1024 * 1024  # 5 Mo
CV_PAGES_MAX = 15  # au-delà, le texte n'est pas lu (CV anormalement long)

Statut = Candidature.Statut

# Transitions autorisées ; « retirée » est réservée à l'apprenant
TRANSITIONS = {
    Statut.ENVOYEE: {Statut.EN_EXAMEN, Statut.REFUSEE, Statut.RETIREE},
    Statut.EN_EXAMEN: {Statut.ENTRETIEN, Statut.REFUSEE, Statut.RETIREE},
    Statut.ENTRETIEN: {Statut.ACCEPTEE, Statut.REFUSEE, Statut.RETIREE},
}


class TransitionInvalide(ValidationError):
    """Changement de statut de candidature interdit par le cycle de vie."""


# ---------- Entreprises (recruteurs) ----------

@transaction.atomic
def inscrire_recruteur(form_utilisateur, form_entreprise):
    """Crée le compte recruteur et son entreprise (en attente) dans une seule transaction."""
    user = form_utilisateur.save()
    entreprise = form_entreprise.save(commit=False)
    entreprise.utilisateur = user
    entreprise.statut = ProfilEntreprise.Statut.EN_ATTENTE
    entreprise.save()
    return user


def entreprise_de(user):
    """Entreprise du recruteur, ou None."""
    try:
        return user.profil_entreprise
    except ProfilEntreprise.DoesNotExist:
        return None


@transaction.atomic
def valider_entreprise(entreprise):
    if entreprise.statut == ProfilEntreprise.Statut.VALIDEE:
        raise ValidationError(f"{entreprise} est déjà validée.")
    entreprise.statut = ProfilEntreprise.Statut.VALIDEE
    entreprise.motif_refus = ""
    entreprise.date_decision = timezone.now()
    entreprise.save(update_fields=["statut", "motif_refus", "date_decision"])
    integrations.entreprise_decidee(entreprise)
    return entreprise


@transaction.atomic
def refuser_entreprise(entreprise, motif):
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Indiquez le motif du refus.")
    entreprise.statut = ProfilEntreprise.Statut.REFUSEE
    entreprise.motif_refus = motif
    entreprise.date_decision = timezone.now()
    entreprise.save(update_fields=["statut", "motif_refus", "date_decision"])
    integrations.entreprise_decidee(entreprise)
    return entreprise


# ---------- Offres ----------

def publier_offre(offre):
    if not offre.entreprise.est_validee:
        raise ValidationError("Votre entreprise doit être validée avant de publier une offre.")
    if offre.statut == Offre.Statut.SUSPENDUE:
        raise ValidationError("Cette offre a été suspendue par la modération : elle ne peut pas être republiée.")
    if offre.est_expiree:
        raise ValidationError("La date limite est passée : modifiez-la avant de publier.")
    offre.statut = Offre.Statut.PUBLIEE
    offre.date_publication = offre.date_publication or timezone.now()
    offre.save(update_fields=["statut", "date_publication", "date_maj"])
    return offre


def fermer_offre(offre):
    if offre.statut != Offre.Statut.PUBLIEE:
        raise ValidationError("Seule une offre publiée peut être fermée.")
    offre.statut = Offre.Statut.FERMEE
    offre.save(update_fields=["statut", "date_maj"])
    return offre


@transaction.atomic
def dupliquer_offre(offre):
    """Copie l'offre en brouillon, avec ses compétences requises."""
    exigences = list(offre.competences_requises.all())
    copie = Offre.objects.create(
        entreprise=offre.entreprise, titre=f"{offre.titre} (copie)"[:150], description=offre.description,
        type_contrat=offre.type_contrat, mode_travail=offre.mode_travail, ville=offre.ville,
        remuneration=offre.remuneration, date_limite=None, statut=Offre.Statut.BROUILLON,
    )
    CompetenceRequise.objects.bulk_create([
        CompetenceRequise(offre=copie, competence_id=e.competence_id, niveau_requis=e.niveau_requis,
                          obligatoire=e.obligatoire)
        for e in exigences
    ])
    return copie


def suspendre_offre(offre):
    offre.statut = Offre.Statut.SUSPENDUE
    offre.save(update_fields=["statut", "date_maj"])
    return offre


def signaler_offre(offre, auteur, motif, details=""):
    if SignalementOffre.objects.filter(offre=offre, auteur=auteur, traite=False).exists():
        raise ValidationError("Vous avez déjà signalé cette offre : la modération va l'examiner.")
    return SignalementOffre.objects.create(offre=offre, auteur=auteur, motif=motif, details=details.strip())


@transaction.atomic
def traiter_signalement(signalement, administrateur, decision):
    """Décision de l'administrateur : suspendre l'offre ou classer sans suite. Renvoie une confirmation."""
    if signalement.traite:
        raise ValidationError("Ce signalement a déjà été traité.")
    if decision == SignalementOffre.Decision.SUSPENDUE:
        suspendre_offre(signalement.offre)
        confirmation = f"L'offre « {signalement.offre.titre} » est suspendue."
    elif decision == SignalementOffre.Decision.CLASSEE:
        confirmation = "Le signalement est classé sans suite."
    else:
        raise ValidationError("Décision inconnue.")
    signalement.traite = True
    signalement.decision = decision
    signalement.traite_par = administrateur
    signalement.date_traitement = timezone.now()
    signalement.save(update_fields=["traite", "decision", "traite_par", "date_traitement"])
    return confirmation


# ---------- Score de compatibilité ----------

@dataclass(frozen=True)
class ResultatScore:
    score: int | None
    obligatoires_manquantes: bool = False

    @property
    def calculable(self):
        return self.score is not None


def arrondir(valeur):
    """Arrondi « scolaire » (0,5 vers le haut), sans les surprises du round() de Python."""
    return math.floor(valeur + Fraction(1, 2))


def calculer_score(exigences, niveaux):
    """Fonction pure : score = round(100 × Σ wᵢ × min(nₐ / nᵣ, 1) / Σ wᵢ).

    `exigences` : itérable de (competence_id, niveau_requis, obligatoire) ;
    `niveaux` : {competence_id: niveau de l'apprenant}. Poids : 2 si obligatoire, 1 sinon.
    """
    total = acquis = 0
    manquantes = False
    for competence_id, niveau_requis, obligatoire in exigences:
        poids = 2 if obligatoire else 1
        niveau = niveaux.get(competence_id, 0)
        total += poids
        acquis += poids * min(Fraction(niveau, niveau_requis), 1)
        if obligatoire and niveau == 0:
            manquantes = True
    if not total:
        return ResultatScore(None)
    return ResultatScore(arrondir(100 * Fraction(acquis) / total), manquantes)


def niveaux_de(apprenant):
    """{competence_id: niveau} de l'apprenant, en une requête."""
    return dict(CompetenceApprenant.objects.filter(profil__apprenant=apprenant)
                .values_list("competence_id", "niveau"))


def exigences_de(offre):
    return [(e.competence_id, e.niveau_requis, e.obligatoire) for e in offre.competences_requises.all()]


def score_offre(offre, apprenant, niveaux=None):
    return calculer_score(exigences_de(offre), niveaux_de(apprenant) if niveaux is None else niveaux)


def scores_offres(apprenant, offres):
    """Calcule le score de chaque offre et l'attache dans `offre.compatibilite`.

    Nombre de requêtes constant : une pour les compétences requises (sauf si déjà préchargées)
    et une pour les niveaux de l'apprenant, quel que soit le nombre d'offres.
    """
    offres = list(offres)
    prefetch_related_objects(offres, "competences_requises")
    niveaux = niveaux_de(apprenant) if apprenant is not None else {}
    for offre in offres:
        offre.compatibilite = calculer_score(exigences_de(offre), niveaux)
    return offres


def trier_par_score(offres):
    """Meilleur score d'abord ; les scores non calculables à la fin."""
    return sorted(offres, key=lambda o: (o.compatibilite.score is None, -(o.compatibilite.score or 0)))


# ---------- Écart de compétences ----------

@dataclass(frozen=True)
class Ecart:
    competence: Competence
    niveau_actuel: int
    niveau_requis: int
    obligatoire: bool

    @property
    def libelle_actuel(self):
        return Niveau(self.niveau_actuel).label if self.niveau_actuel else "aucun"

    @property
    def libelle_requis(self):
        return Niveau(self.niveau_requis).label

    def __str__(self):
        texte = f"{self.competence.nom} ({self.libelle_actuel} → {self.libelle_requis}"
        return texte + (", obligatoire)" if self.obligatoire else ")")


def ecart_competences(offre, apprenant, niveaux=None):
    """Compétences où l'apprenant est sous le niveau requis : obligatoires d'abord, puis écart décroissant."""
    niveaux = niveaux_de(apprenant) if niveaux is None else niveaux
    prefetch_related_objects([offre], "competences_requises__competence")
    ecarts = [
        Ecart(e.competence, niveaux.get(e.competence_id, 0), e.niveau_requis, e.obligatoire)
        for e in offre.competences_requises.all()
        if niveaux.get(e.competence_id, 0) < e.niveau_requis
    ]
    return sorted(ecarts, key=lambda e: (not e.obligatoire, -(e.niveau_requis - e.niveau_actuel), e.competence.nom))


def formater_ecart(ecarts):
    """« Il te manque : Airflow (aucun → Intermédiaire, obligatoire), Power BI (Notions → Avancé) »."""
    if not ecarts:
        return "Tu as toutes les compétences demandées."
    return "Il te manque : " + ", ".join(str(e) for e in ecarts)


def competences_prioritaires(apprenant, limite=5):
    """Compétences les plus demandées dans les offres ouvertes que l'apprenant n'a pas au niveau requis."""
    niveau_apprenant = CompetenceApprenant.objects.filter(
        profil__apprenant=apprenant, competence=OuterRef("competence")).values("niveau")[:1]
    return list(
        CompetenceRequise.objects.filter(offre__in=Offre.objects.ouvertes())
        .annotate(niveau_apprenant=Coalesce(Subquery(niveau_apprenant, output_field=IntegerField()), Value(0)))
        .filter(niveau_apprenant__lt=F("niveau_requis"))
        .values("competence_id", "competence__nom", "competence__categorie")
        .annotate(nb_offres=Count("offre", distinct=True))
        .order_by("-nb_offres", "competence__nom")[:limite]
    )


# ---------- Profil carrière et CV ----------

def obtenir_profil(apprenant):
    profil, _ = ProfilCarriere.objects.get_or_create(apprenant=apprenant)
    return profil


def completude_profil(profil, nb_competences=None):
    """Pourcentage de complétude : chaque critère rempli compte autant."""
    if profil is None:
        return 0
    if nb_competences is None:
        nb_competences = profil.competences.count()
    criteres = [
        profil.titre, profil.presentation, profil.ville, profil.disponibilite, profil.types_contrat_recherches,
        profil.cv, profil.lien_github or profil.lien_linkedin or profil.lien_portfolio, nb_competences >= 3,
    ]
    return round(100 * sum(bool(c) for c in criteres) / len(criteres))


def valider_cv(fichier):
    """PDF uniquement (extension et octets magiques), 5 Mo maximum."""
    if Path(fichier.name).suffix.lower() != ".pdf":
        raise ValidationError("Le CV doit être un fichier PDF.")
    if fichier.size > CV_TAILLE_MAX:
        raise ValidationError(f"Le CV dépasse la taille maximale ({filesizeformat(CV_TAILLE_MAX)}).")
    fichier.seek(0)
    entete = fichier.read(4)
    fichier.seek(0)
    if entete != b"%PDF":
        raise ValidationError("Ce fichier n'est pas un vrai PDF.")


def normaliser(texte):
    """Minuscules, sans accents, espaces simplifiés : « Modélisation  UML » → « modelisation uml »."""
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", texte)


def extraire_texte_pdf(fichier):
    """Texte du PDF, ou chaîne vide s'il est illisible (PDF scanné, corrompu...)."""
    from pypdf import PdfReader

    try:
        fichier.seek(0)
        lecteur = PdfReader(fichier)
        if len(lecteur.pages) > CV_PAGES_MAX:
            return ""
        texte = "\n".join(page.extract_text() or "" for page in lecteur.pages)
    except Exception:  # un CV illisible ne doit jamais provoquer d'erreur
        logger.info("CV illisible, aucune suggestion", exc_info=True)
        texte = ""
    finally:
        fichier.seek(0)
    return texte


def suggerer_competences(texte, exclure_ids=()):
    """Compétences du référentiel dont le nom ou un alias apparaît dans le texte."""
    texte = normaliser(texte)
    if not texte.strip():
        return []
    trouvees = []
    for competence in Competence.objects.exclude(pk__in=exclure_ids):
        for terme in [competence.nom, *competence.liste_alias()]:
            terme = normaliser(terme).strip()
            if terme and re.search(rf"(?<![a-z0-9]){re.escape(terme)}(?![a-z0-9])", texte):
                trouvees.append(competence)
                break
    return trouvees


@transaction.atomic
def enregistrer_cv(profil, fichier):
    """Remplace le CV du profil et renvoie les compétences suggérées (rien n'est ajouté automatiquement)."""
    valider_cv(fichier)
    texte = extraire_texte_pdf(fichier)
    if profil.cv:
        profil.cv.delete(save=False)
    profil.cv = fichier
    profil.save(update_fields=["cv", "date_maj"])
    deja = profil.competences.values_list("competence_id", flat=True)
    return suggerer_competences(texte, exclure_ids=list(deja))


def ajouter_competences(profil, competence_ids, niveau=Niveau.NOTIONS):
    """Ajoute les compétences cochées (niveau « Notions » par défaut). Renvoie le nombre ajouté."""
    deja = set(profil.competences.values_list("competence_id", flat=True))
    nouvelles = [CompetenceApprenant(profil=profil, competence=c, niveau=niveau)
                 for c in Competence.objects.filter(pk__in=competence_ids).exclude(pk__in=deja)]
    CompetenceApprenant.objects.bulk_create(nouvelles)
    return len(nouvelles)


# ---------- Candidatures ----------

def raison_refus_candidature(offre, apprenant):
    """Pourquoi l'apprenant ne peut pas postuler (texte), ou None s'il le peut."""
    if not apprenant.est_apprenant:
        return "Seuls les apprenants peuvent postuler."
    if offre.entreprise.statut != ProfilEntreprise.Statut.VALIDEE:
        return "L'entreprise qui publie cette offre n'est pas validée."
    if offre.statut != Offre.Statut.PUBLIEE:
        return "Cette offre n'accepte pas de candidatures."
    if offre.est_expiree:
        return "La date limite de candidature est passée."
    if Candidature.objects.filter(offre=offre, apprenant=apprenant).exists():
        return "Tu as déjà postulé à cette offre."
    return None


def postuler(offre, apprenant, lettre_motivation=""):
    raison = raison_refus_candidature(offre, apprenant)
    if raison:
        raise ValidationError(raison)

    profil = ProfilCarriere.objects.filter(apprenant=apprenant).first()
    candidature = Candidature(offre=offre, apprenant=apprenant, lettre_motivation=lettre_motivation.strip(),
                              score_au_depot=score_offre(offre, apprenant).score)
    try:
        with transaction.atomic():
            if profil and profil.cv:
                # Copie figée : le recruteur voit le CV envoyé, même si l'apprenant change le sien ensuite
                with profil.cv.open("rb") as source:
                    candidature.cv_depose.save("cv.pdf", ContentFile(source.read()), save=False)
            candidature.save()
            _historiser(candidature, "", Statut.ENVOYEE, apprenant)
            integrations.nouvelle_candidature(candidature)
    except IntegrityError:  # double clic : la contrainte d'unicité a joué
        if candidature.cv_depose:
            candidature.cv_depose.delete(save=False)
        raise ValidationError("Tu as déjà postulé à cette offre.")
    return candidature


def _historiser(candidature, ancien, nouveau, auteur, commentaire=""):
    return HistoriqueCandidature.objects.create(candidature=candidature, ancien_statut=ancien,
                                                nouveau_statut=nouveau, auteur=auteur, commentaire=commentaire)


def est_recruteur_de(user, candidature):
    return candidature.offre.entreprise.utilisateur_id == user.pk


def statuts_possibles(candidature, user):
    """Statuts vers lesquels cet utilisateur peut faire passer la candidature (pour les menus)."""
    suivants = TRANSITIONS.get(candidature.statut, set())
    if user.pk == candidature.apprenant_id:
        return [Statut.RETIREE] if Statut.RETIREE in suivants else []
    return [s for s in Statut if s in suivants and s != Statut.RETIREE]


def _verifier_entretien(date_entretien, lieu):
    if not date_entretien or not (lieu or "").strip():
        raise TransitionInvalide("Un entretien demande une date et un lieu (ou un lien de visioconférence).")
    if date_entretien <= timezone.now():
        raise TransitionInvalide("La date de l'entretien doit être dans le futur.")


@transaction.atomic
def changer_statut(candidature, auteur, nouveau, *, commentaire="", date_entretien=None, lieu=""):
    """Fait avancer une candidature dans son cycle de vie. Lève TransitionInvalide sinon."""
    ancien = candidature.statut
    commentaire = (commentaire or "").strip()

    if nouveau not in Statut.values:
        raise TransitionInvalide("Statut inconnu.")
    if nouveau == Statut.RETIREE:
        if auteur.pk != candidature.apprenant_id:
            raise TransitionInvalide("Seul le candidat peut retirer sa candidature.")
    elif not (est_recruteur_de(auteur, candidature) or auteur.est_administrateur):
        raise PermissionDenied("Cette candidature ne concerne pas vos offres.")

    if nouveau not in TRANSITIONS.get(ancien, set()):
        raise TransitionInvalide(f"Passage de « {Statut(ancien).label} » à « {Statut(nouveau).label} » impossible.")

    champs = ["statut", "date_maj"]
    if nouveau == Statut.ENTRETIEN:
        _verifier_entretien(date_entretien, lieu)
        candidature.date_entretien = date_entretien
        candidature.lieu_ou_lien_entretien = lieu.strip()
        champs += ["date_entretien", "lieu_ou_lien_entretien"]
    if nouveau != Statut.RETIREE:
        if candidature.date_premiere_reponse is None:
            candidature.date_premiere_reponse = timezone.now()
            champs.append("date_premiere_reponse")
        if commentaire:
            candidature.message_recruteur = commentaire
            champs.append("message_recruteur")

    candidature.statut = nouveau
    candidature.save(update_fields=champs)
    _historiser(candidature, ancien, nouveau, auteur, commentaire)
    integrations.statut_candidature_change(candidature, ancien)
    return candidature


@transaction.atomic
def planifier_entretien(candidature, recruteur, date_entretien, lieu, commentaire=""):
    """Convoque à un entretien, ou le déplace si la candidature y est déjà."""
    if candidature.statut != Statut.ENTRETIEN:
        return changer_statut(candidature, recruteur, Statut.ENTRETIEN, commentaire=commentaire,
                              date_entretien=date_entretien, lieu=lieu)
    if not (est_recruteur_de(recruteur, candidature) or recruteur.est_administrateur):
        raise PermissionDenied("Cette candidature ne concerne pas vos offres.")
    _verifier_entretien(date_entretien, lieu)
    candidature.date_entretien = date_entretien
    candidature.lieu_ou_lien_entretien = lieu.strip()
    if commentaire:
        candidature.message_recruteur = commentaire.strip()
    candidature.save(update_fields=["date_entretien", "lieu_ou_lien_entretien", "message_recruteur", "date_maj"])
    _historiser(candidature, Statut.ENTRETIEN, Statut.ENTRETIEN, recruteur, commentaire or "Entretien replanifié.")
    integrations.statut_candidature_change(candidature, Statut.ENTRETIEN)
    return candidature


def retirer_candidature(candidature, apprenant):
    return changer_statut(candidature, apprenant, Statut.RETIREE)


# ---------- Kanban et tableaux de bord ----------

COLONNES_KANBAN = [Statut.ENVOYEE, Statut.EN_EXAMEN, Statut.ENTRETIEN, Statut.ACCEPTEE, Statut.REFUSEE,
                   Statut.RETIREE]


def scores_candidatures(offre, candidatures):
    """Score actuel de chaque candidat pour l'offre, en une requête pour tous les niveaux."""
    candidatures = list(candidatures)
    exigences = exigences_de(offre)
    niveaux = {}
    for apprenant_id, competence_id, niveau in CompetenceApprenant.objects.filter(
            profil__apprenant__in=[c.apprenant_id for c in candidatures]).values_list(
            "profil__apprenant_id", "competence_id", "niveau"):
        niveaux.setdefault(apprenant_id, {})[competence_id] = niveau
    for c in candidatures:
        c.compatibilite = calculer_score(exigences, niveaux.get(c.apprenant_id, {}))
    return candidatures


def colonnes_kanban(offre):
    """[(statut, [candidatures triées par score décroissant])...] pour le Kanban d'une offre."""
    prefetch_related_objects([offre], "competences_requises")
    candidatures = scores_candidatures(offre, offre.candidatures.select_related("apprenant"))
    colonnes = {statut: [] for statut in COLONNES_KANBAN}
    for c in trier_par_score(candidatures):
        colonnes[c.statut].append(c)
    return [(statut, colonnes[statut]) for statut in COLONNES_KANBAN]


def tableau_recruteur(recruteur):
    offres = Offre.objects.de(recruteur)
    candidatures = Candidature.objects.filter(offre__entreprise__utilisateur=recruteur)
    return {
        "offres_actives": offres.ouvertes().annotate(nb_candidatures=Count("candidatures"))[:10],
        "nb_offres_actives": offres.ouvertes().count(),
        "nb_brouillons": offres.filter(statut=Offre.Statut.BROUILLON).count(),
        "nouvelles_candidatures": candidatures.filter(statut=Statut.ENVOYEE)
        .select_related("apprenant", "offre").order_by("-date_creation")[:8],
        "nb_nouvelles": candidatures.filter(statut=Statut.ENVOYEE).count(),
        "entretiens": candidatures.filter(statut=Statut.ENTRETIEN, date_entretien__gte=timezone.now())
        .select_related("apprenant", "offre").order_by("date_entretien")[:8],
    }


# ---------- Statistiques (administrateur) ----------

def statistiques():
    aujourdhui = timezone.localdate()
    # Une offre publiée dont la date limite est passée compte comme fermée
    statut_effectif = Case(
        When(statut=Offre.Statut.PUBLIEE, date_limite__lt=aujourdhui, then=Value(Offre.Statut.FERMEE)),
        default=F("statut"),
    )
    par_statut = dict(Offre.objects.annotate(s=statut_effectif).values_list("s").annotate(n=Count("id")))
    offres_par_statut = [(label, par_statut.get(valeur, 0)) for valeur, label in Offre.Statut.choices]

    candidatures = Candidature.objects.aggregate(
        total=Count("id"),
        acceptees=Count("id", filter=Q(statut=Statut.ACCEPTEE)),
        cloturees=Count("id", filter=Q(statut__in=[Statut.ACCEPTEE, Statut.REFUSEE])),
        delai=Avg(ExpressionWrapper(F("date_premiere_reponse") - F("date_creation"), output_field=DurationField()),
                  filter=Q(date_premiere_reponse__isnull=False)),
    )
    taux = round(100 * candidatures["acceptees"] / candidatures["cloturees"]) if candidatures["cloturees"] else None

    diffusees = Offre.objects.exclude(statut=Offre.Statut.BROUILLON)
    libelles_contrat = dict(TypeContrat.choices)
    return {
        "offres_par_statut": offres_par_statut,
        "nb_offres": sum(n for _, n in offres_par_statut),
        "nb_candidatures": candidatures["total"],
        "taux_acceptation": taux,
        "delai_moyen": candidatures["delai"],
        "top_competences": list(
            CompetenceRequise.objects.filter(offre__in=diffusees).values("competence__nom")
            .annotate(nb_offres=Count("offre", distinct=True)).order_by("-nb_offres", "competence__nom")[:10]),
        "par_contrat": [(libelles_contrat.get(t, t), n) for t, n in
                        diffusees.values_list("type_contrat").annotate(n=Count("id")).order_by("-n")],
        "entreprises_en_attente": ProfilEntreprise.objects.filter(statut=ProfilEntreprise.Statut.EN_ATTENTE).count(),
        "signalements_a_traiter": SignalementOffre.objects.filter(traite=False).count(),
    }


def formater_duree(duree):
    """timedelta → « 2 j 5 h », « 3 h 10 min » ou « 12 min »."""
    if duree is None:
        return "—"
    minutes = int(duree / timedelta(minutes=1))
    jours, minutes = divmod(minutes, 24 * 60)
    heures, minutes = divmod(minutes, 60)
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes} min"
    return f"{minutes} min"
