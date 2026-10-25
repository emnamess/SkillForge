from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Entraîne le classifieur local d'intentions de l'assistant de leçon."

    def handle(self, *args, **options):
        from django.conf import settings
        from apps.courses.ai_assistant.train_model import train
        import json
        base = settings.BASE_DIR / "apps/courses/ai_assistant"
        dataset, artifact = base / "dataset.csv", base / "models/intention.joblib"
        if not dataset.exists():
            raise CommandError("Dataset absent. Lancez generate_lesson_ai_dataset d'abord.")
        metrics = train(dataset, artifact)
        self.stdout.write(self.style.SUCCESS(f"Modèle sauvegardé : {artifact}"))
        self.stdout.write(json.dumps(metrics, ensure_ascii=False, indent=2))
