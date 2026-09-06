from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ml_model import FEATURES, MODEL_PATH, METRICS_PATH

DATASET = ROOT / "data" / "real_training_dataset.csv"


def make_model():
    return Pipeline([
        ("scale", StandardScaler()),
        (
            "rf",
            RandomForestClassifier(
                n_estimators=500,
                max_depth=18,
                min_samples_leaf=2,
                max_features="sqrt",
                class_weight="balanced_subsample",
                random_state=26001,
                n_jobs=-1,
            ),
        ),
    ])


def split_data(df):
    years = sorted(df.event_year.unique().tolist())

    train_years = [y for y in years if y <= 2022]
    valid_years = [y for y in years if y in (2023, 2024)]
    test_years = [y for y in years if y == 2025]

    train_temporal = df[df.event_year.isin(train_years)]
    valid_temporal = df[df.event_year.isin(valid_years)]
    test_temporal = df[df.event_year.isin(test_years)]

    if (
        len(train_temporal) >= 100
        and train_temporal.landslide_occurred.nunique() == 2
        and len(valid_temporal) >= 20
        and valid_temporal.landslide_occurred.nunique() == 2
        and len(test_temporal) >= 20
        and test_temporal.landslide_occurred.nunique() == 2
    ):
        return (
            train_temporal,
            valid_temporal,
            test_temporal,
            "temporal: train<=2022, validation=2023-2024, test=2025",
        )

    train_valid, test = train_test_split(
        df,
        test_size=0.15,
        random_state=26001,
        stratify=df["landslide_occurred"],
    )

    train, valid = train_test_split(
        train_valid,
        test_size=(0.15 / 0.85),
        random_state=26001,
        stratify=train_valid["landslide_occurred"],
    )

    return (
        train,
        valid,
        test,
        "stratified random prototype split: 70% train / 15% validation / 15% test",
    )


def score(model, frame):
    probabilities = model.predict_proba(frame[FEATURES])[:, 1]

    y = frame.landslide_occurred.astype(int)

    predictions = (probabilities >= 0.5).astype(int)

    return {
        "samples": int(len(frame)),
        "positive_samples": int(y.sum()),
        "negative_samples": int((y == 0).sum()),
        "accuracy": round(
            float(accuracy_score(y, predictions)),
            4,
        ),
        "precision": round(
            float(precision_score(y, predictions, zero_division=0)),
            4,
        ),
        "recall": round(
            float(recall_score(y, predictions, zero_division=0)),
            4,
        ),
        "f1": round(
            float(f1_score(y, predictions, zero_division=0)),
            4,
        ),
        "roc_auc": (
            round(float(roc_auc_score(y, probabilities)), 4)
            if y.nunique() == 2
            else None
        ),
        "confusion_matrix": confusion_matrix(
            y,
            predictions,
        ).tolist(),
    }


def main():
    if not DATASET.exists():
        raise SystemExit(
            f"Missing {DATASET}. Run build_real_dataset.py first."
        )

    df = pd.read_csv(DATASET)

    df["event_year"] = pd.to_numeric(
        df["event_year"],
        errors="coerce",
    )

    df = df.dropna(
        subset=FEATURES + [
            "landslide_occurred",
            "event_year",
        ]
    )

    df["event_year"] = df["event_year"].astype(int)

    if len(df) < 200:
        raise SystemExit(
            f"Need at least 200 valid rows. Found {len(df)}."
        )

    if df.landslide_occurred.nunique() != 2:
        raise SystemExit(
            "Dataset must contain both landslide and background samples."
        )

    print()
    print("=" * 60)
    print("SLOPENEXIS REAL-DATA MODEL TRAINING")
    print("=" * 60)

    print(f"Dataset: {DATASET}")
    print(f"Total samples: {len(df)}")
    print(
        f"Landslide samples: "
        f"{int(df.landslide_occurred.sum())}"
    )
    print(
        f"Background samples: "
        f"{int((df.landslide_occurred == 0).sum())}"
    )

    print()
    print("Years:")
    print(
        df.groupby("event_year")["landslide_occurred"]
        .agg(["count", "sum"])
        .to_string()
    )

    train, valid, test, validation_strategy = split_data(df)

    print()
    print("Split strategy:")
    print(validation_strategy)

    print()
    print("Train:")
    print(f"  Samples: {len(train)}")
    print(
        f"  Landslides: "
        f"{int(train.landslide_occurred.sum())}"
    )

    print("Validation:")
    print(f"  Samples: {len(valid)}")
    print(
        f"  Landslides: "
        f"{int(valid.landslide_occurred.sum())}"
    )

    print("Test:")
    print(f"  Samples: {len(test)}")
    print(
        f"  Landslides: "
        f"{int(test.landslide_occurred.sum())}"
    )

    model = make_model()

    model.fit(
        train[FEATURES],
        train.landslide_occurred.astype(int),
    )

    metrics = {
        "dataset": "real_training_dataset.csv",
        "mode": "REAL_DATA",
        "period": (
            f"{int(df.event_year.min())}-"
            f"{int(df.event_year.max())}"
        ),
        "samples": int(len(df)),
        "positive_samples": int(
            df.landslide_occurred.sum()
        ),
        "negative_background_samples": int(
            (df.landslide_occurred == 0).sum()
        ),
        "train_samples": int(len(train)),
        "validation_samples": int(len(valid)),
        "test_samples": int(len(test)),
        "validation_strategy": validation_strategy,
        "test": score(model, test),
        "feature_columns": FEATURES,
        "model": (
            "RandomForestClassifier("
            "n_estimators=500,"
            "max_depth=18,"
            "min_samples_leaf=2,"
            "max_features=sqrt,"
            "class_weight=balanced_subsample)"
        ),
        "warning": (
            "NASA COOLR/GLC is an observed/reporting inventory, "
            "not exhaustive ground truth; background label 0 is "
            "not proof of no unreported landslide."
        ),
    }

    if (
        len(valid)
        and valid.landslide_occurred.nunique() == 2
    ):
        metrics["validation"] = score(
            model,
            valid,
        )

    final_model = make_model()

    final_model.fit(
        df[FEATURES],
        df.landslide_occurred.astype(int),
    )

    joblib.dump(
        final_model,
        MODEL_PATH,
    )

    METRICS_PATH.write_text(
        json.dumps(
            metrics,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)

    print(
        json.dumps(
            metrics,
            indent=2,
        )
    )

    print()
    print(
        f"Final model trained on all "
        f"{len(df)} historical samples"
    )

    print(
        f"Saved model: {MODEL_PATH}"
    )

    print(
        f"Saved metrics: {METRICS_PATH}"
    )


if __name__ == "__main__":
    main()