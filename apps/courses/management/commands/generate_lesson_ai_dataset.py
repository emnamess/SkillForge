from django.core.management.base import BaseCommand
from apps.courses.ai_assistant.dataset_generator import generate_dataset


class Command(BaseCommand):
    help = "Génère le dataset synthétique des intentions de l'assistant de leçon."

    def add_arguments(self, parser):
        parser.add_argument("--variations", type=int, default=6, help="Nombre de formulations distinctes par intention (4 à 6).")

    def handle(self, *args, variations=6, **options):
        from django.conf import settings
        path = settings.BASE_DIR / "apps/courses/ai_assistant/dataset.csv"
        try:
            generate_dataset(path, variations=variations)
        except ValueError as exc:
            from django.core.management.base import CommandError
            raise CommandError(str(exc)) from exc
        import csv
        with path.open(encoding="utf-8", newline="") as source:
            count = sum(1 for _ in csv.DictReader(source))
        self.stdout.write(self.style.SUCCESS(f"Dataset synthétique créé : {count} exemples ({path})"))
