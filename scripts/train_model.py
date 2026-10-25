"""
scripts/train_model.py

Trains the risk model, evaluates it on a held-out split and writes
models/risk_model.joblib (not versioned) + models/model_card.json.

    python scripts/train_model.py                  # default: ./models
    python scripts/train_model.py --out-dir /tmp/m
    python scripts/train_model.py --model random_forest   # or set RISK_MODEL

Docker builds and CI run this before starting the app; the app itself never
trains at startup (it fails with a clear ModelLoadError if the files are missing).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import MODEL_TYPES  # noqa: E402
from learning_module.training_pipeline import run_training  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and persist the risk model.")
    parser.add_argument("--out-dir", type=Path, default=None, help="where to write the artifacts")
    parser.add_argument("--model", choices=MODEL_TYPES, default=None,
                        help="model to train (default: RISK_MODEL or the validated one)")
    args = parser.parse_args()
    card = run_training(args.out_dir, args.model)
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
