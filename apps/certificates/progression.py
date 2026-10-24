"""Suivi de progression des apprenants.

La progression est stockée par le module cours (modèle `Inscription`, champ `progression`, voir le
diagramme de classes). Ce fichier la lit sans en dépendre directement : tant que le module cours n'est
pas fusionné, `inscriptions_disponibles()` renvoie False et les pages affichent un message d'attente.

Champs attendus sur courses.Inscription : `apprenant`, `cours` (avec `titre` et `formateur`),
`progression` (0 à 100) et `date_inscription`. Si les noms changent, il suffit d'adapter CHAMPS.
"""

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist

from .models import Certificat

CHAMPS = {
    "apprenant": "apprenant",
    "cours": "cours",
    "progression": "progression",
    "date": "date_inscription",
    "titre_cours": "titre",
    "formateur_cours": "formateur",
}


def modele_inscription():
    try:
        modele = apps.get_model("courses", "Inscription")
    except LookupError:
        return None
    try:
        for champ in ("apprenant", "cours", "progression"):
            modele._meta.get_field(CHAMPS[champ])
    except FieldDoesNotExist:
        return None
    return modele


def inscriptions_disponibles():
    return modele_inscription() is not None


def inscriptions_pour(user):
    """Inscriptions visibles par l'utilisateur : les siennes (apprenant), celles de ses cours (formateur),
    toutes (administrateur). Renvoie None si le module cours n'est pas encore disponible."""
    Inscription = modele_inscription()
    if Inscription is None:
        return None
    qs = Inscription.objects.select_related(CHAMPS["apprenant"], CHAMPS["cours"])
    if user.est_administrateur:
        return qs
    if user.est_formateur:
        return qs.filter(**{f"{CHAMPS['cours']}__{CHAMPS['formateur_cours']}": user})
    return qs.filter(**{CHAMPS["apprenant"]: user})


def lignes_progression(user, limite=None):
    """Liste de dicts prêts pour le template, triés par progression décroissante."""
    qs = inscriptions_pour(user)
    if qs is None:
        return None
    qs = qs.order_by(f"-{CHAMPS['progression']}")
    if limite:
        qs = qs[:limite]

    certifies = set(Certificat.objects.filter(statut=Certificat.Statut.VALIDE)
                    .values_list("apprenant_id", "titre_cours"))
    lignes = []
    for inscription in qs:
        apprenant = getattr(inscription, CHAMPS["apprenant"])
        cours = getattr(inscription, CHAMPS["cours"])
        titre = getattr(cours, CHAMPS["titre_cours"], str(cours))
        progression = getattr(inscription, CHAMPS["progression"]) or 0
        lignes.append({
            "apprenant": apprenant,
            "cours": titre,
            "progression": max(0, min(100, round(progression))),
            "date": getattr(inscription, CHAMPS["date"], None),
            "certifie": (apprenant.pk, titre) in certifies,
        })
    return lignes
