import re

from django import template
from django.template.defaultfilters import filesizeformat
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def surligner(texte, terme):
    """Met en évidence le terme recherché ; le texte est échappé avant d'ajouter <mark>."""
    texte = escape(texte or "")
    if not terme:
        return mark_safe(texte)
    motif = re.compile(re.escape(escape(terme)), re.IGNORECASE)
    return mark_safe(motif.sub(lambda m: f"<mark>{m.group(0)}</mark>", texte))


@register.filter
def taille(octets):
    return filesizeformat(octets).replace("bytes", "octets").replace("KB", "Ko").replace("MB", "Mo")
