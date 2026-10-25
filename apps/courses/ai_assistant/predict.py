"""Chargement/cache du classifieur et script autonome de prédiction.

Depuis la racine du dépôt :
    python -m apps.courses.ai_assistant.predict "Résume cette leçon"
"""
import argparse
from functools import lru_cache
from pathlib import Path

import joblib

ARTIFACT = Path(__file__).resolve().parent / "models" / "intention.joblib"


@lru_cache(maxsize=1)
def _load(artifact_path=str(ARTIFACT)):
    return joblib.load(artifact_path)


def predict_intent(question, artifact_path=ARTIFACT):
    if not question.strip():
        raise ValueError("La question ne peut pas être vide.")
    if len(question) > 500:
        raise ValueError("La question ne peut pas dépasser 500 caractères.")
    path = Path(artifact_path)
    if not path.exists():
        raise FileNotFoundError(f"Modèle absent : {path}. Lancez train_lesson_ai après la génération du dataset.")
    return _load(str(path)).predict([question.strip()])[0]


def main():
    parser = argparse.ArgumentParser(description="Prédit le type d'aide pédagogique demandé.")
    parser.add_argument("question", help="Question de l'apprenant à classifier")
    parser.add_argument("--model", type=Path, default=ARTIFACT, help="Chemin du pipeline joblib sauvegardé")
    args = parser.parse_args()
    print(predict_intent(args.question, args.model))


if __name__ == "__main__":
    main()
