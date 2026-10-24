from django.conf import settings
from django.core.management.base import BaseCommand

from apps.quizzes.services import _client_gemini, obtenir_cle_gemini


class Command(BaseCommand):
    help = "Vérifie la clé Gemini et liste les modèles disponibles."

    def handle(self, *args, **options):
        cle = obtenir_cle_gemini()
        self.stdout.write(f"Clé détectée : {cle[:8]}...{cle[-4:] if len(cle) > 12 else ''} (Longueur: {len(cle)})")

        if not cle:
            self.stdout.write(self.style.ERROR("❌ Aucune clé GEMINI_API_KEY dans .env"))
            return

        client = _client_gemini()
        self.stdout.write("Connexion à l'API Google Gemini...")

        try:
            modeles = []
            for m in client.models.list():
                nom = getattr(m, "name", str(m))
                actions = getattr(m, "supported_actions", [])
                modeles.append(nom)

            self.stdout.write(self.style.SUCCESS(f"✅ {len(modeles)} modèle(s) accessibles avec cette clé :"))
            for m in modeles[:10]:
                self.stdout.write(f"  - {m}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Erreur lors de l'appel à Gemini : {e}"))
            self.stdout.write("\n💡 Cause fréquente :")
            self.stdout.write("1. La clé a été créée dans Google Cloud sans activer 'Generative Language API'.")
            self.stdout.write("2. Rendez-vous sur https://aistudio.google.com/apikey et cliquez sur 'Create API key in new project'.")
