"""Entraîne le routeur d'intentions et évalue les sujets entièrement retenus."""
import csv
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.pipeline import FeatureUnion, make_pipeline
from sklearn.svm import LinearSVC


def train(dataset, artifact):
    with Path(dataset).open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    partitions = {split: [row for row in rows if row["split"] == split] for split in ("train", "validation", "test")}
    if any(not items for items in partitions.values()):
        raise ValueError("Le dataset doit contenir les partitions train, validation et test.")
    train_rows = partitions["train"]
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), strip_accents="unicode", sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True)),
    ])
    model = make_pipeline(features, LinearSVC(class_weight="balanced"))
    model.fit([row["question"] for row in train_rows], [row["intent"] for row in train_rows])

    metrics = {"samples": {split: len(items) for split, items in partitions.items()}, "partitions": {}}
    for split in ("validation", "test"):
        items = partitions[split]
        expected = [row["intent"] for row in items]
        predicted = model.predict([row["question"] for row in items])
        metrics["partitions"][split] = {
            "accuracy": accuracy_score(expected, predicted),
            "f1_macro": f1_score(expected, predicted, average="macro", zero_division=0),
            "classification_report": classification_report(expected, predicted, zero_division=0, output_dict=True),
            "subjects": sorted({row["subject_id"] for row in items}),
        }
    target = Path(artifact)
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, target)
    return metrics
