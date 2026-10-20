from django.conf import settings
from django.core.management.base import BaseCommand

from apps.notifications.moderation import _resume_erreur, ia_disponible, moderer_par_gemini, moderer_par_regles

EXEMPLES = [
    "Bonjour, j'ai une question sur les jointures SQL",
    "ce module est nul, je ne comprends rien",
    "you are useless",
    "envoie-moi les réponses du quiz stp",
    "import pandas as pd puis kill le process",
]


class Command(BaseCommand):
    help = "Compare la décision de Gemini et celle des règles locales (vérifie aussi la clé API)."

    def add_arguments(self, parser):
        parser.add_argument("textes", nargs="*", help="Messages à analyser (exemples par défaut).")

    def handle(self, *args, textes, **options):
        self.stdout.write(f"Modèle : {settings.GEMINI_MODEL} · réflexion : {settings.GEMINI_REFLEXION or 'défaut'}")
        if not ia_disponible():
            self.stdout.write(self.style.WARNING(
                "IA inactive : GEMINI_API_KEY vide ou MODERATION_IA_ACTIVE=False dans .env. Seules les règles répondent."))

        for texte in textes or EXEMPLES:
            self.stdout.write(f"\n« {texte} »")
            regles = moderer_par_regles(texte)
            self.stdout.write(f"  Règles locales : {regles.decision:<9} {regles.categorie}")
            if not ia_disponible():
                continue
            try:
                gemini = moderer_par_gemini(texte)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Gemini         : ERREUR {_resume_erreur(e)}"))
                continue
            style = self.style.ERROR if gemini.bloque else self.style.WARNING if not gemini.autorise else self.style.SUCCESS
            self.stdout.write(style(f"  Gemini         : {gemini.decision:<9} {gemini.categorie}  → {gemini.raison}"))
