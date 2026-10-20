import time

from django.core.management.base import BaseCommand

from apps.notifications.services import envoyer_rappels_dus


class Command(BaseCommand):
    help = "Envoie les rappels arrivés à échéance (à lancer chaque minute par le planificateur de tâches)."

    def add_arguments(self, parser):
        parser.add_argument("--boucle", action="store_true",
                            help="Tourne en continu (pratique en développement).")
        parser.add_argument("--intervalle", type=int, default=60,
                            help="Secondes entre deux vérifications avec --boucle (défaut : 60).")

    def handle(self, *args, boucle=False, intervalle=60, **options):
        if not boucle:
            self.envoyer()
            return

        self.stdout.write(f"Vérification des rappels toutes les {intervalle} s (Ctrl+C pour arrêter).")
        try:
            while True:
                self.envoyer()
                time.sleep(intervalle)
        except KeyboardInterrupt:
            self.stdout.write("Arrêt.")

    def envoyer(self):
        n = envoyer_rappels_dus()
        if n:
            self.stdout.write(self.style.SUCCESS(f"{n} rappel(s) envoyé(s)."))
