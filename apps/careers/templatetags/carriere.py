import math

from django import template

from ..models import Niveau

register = template.Library()

RAYON_JAUGE = 52
CIRCONFERENCE = 2 * math.pi * RAYON_JAUGE


@register.filter
def classe_score(score):
    """Couleur du badge de compatibilité."""
    if score is None:
        return "score-na"
    if score >= 75:
        return "score-haut"
    if score >= 50:
        return "score-moyen"
    return "score-bas"


@register.filter
def libelle_niveau(niveau):
    return Niveau(niveau).label if niveau else "aucun"


@register.inclusion_tag("careers/partials/jauge.html")
def jauge(resultat):
    """Jauge circulaire SVG du score de compatibilité."""
    score = resultat.score if resultat else None
    return {
        "resultat": resultat,
        "score": score,
        "rayon": RAYON_JAUGE,
        "circonference": f"{CIRCONFERENCE:.2f}",
        "decalage": f"{CIRCONFERENCE * (1 - (score or 0) / 100):.2f}",
    }
