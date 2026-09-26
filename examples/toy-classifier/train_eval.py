"""Train one model and write test predictions through the Hypothex SDK."""

import argparse
import json
import pickle
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier

import hypothex as hx

HERE = Path(__file__).parent


def load(split: str) -> list[dict]:
    """Read one split."""
    text = (HERE / "data" / f"{split}.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def build(model: str, seed: int):  # noqa: ANN201 - returns an sklearn estimator
    """Create the estimator."""
    if model == "logreg":
        return LogisticRegression(max_iter=1000, random_state=seed)
    if model == "rf":
        return RandomForestClassifier(n_estimators=50, random_state=seed)
    if model == "knn":
        return KNeighborsClassifier(n_neighbors=5)
    raise SystemExit(f"unknown model {model!r}")


def main() -> None:
    """Fit, log train accuracy, write predictions and a checkpoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    run = hx.current()
    train, test = load("train"), load("test")
    clf = build(args.model, args.seed)
    clf.fit([r["x"] for r in train], [r["reference"] for r in train])
    run.log(
        {
            "train_accuracy": float(
                clf.score([r["x"] for r in train], [r["reference"] for r in train])
            )
        }
    )
    preds = clf.predict([r["x"] for r in test])
    run.log_predictions(
        {"id": r["id"], "prediction": int(p)} for r, p in zip(test, preds, strict=True)
    )
    if isinstance(run, hx.Run):
        ckpt = run.run_dir / "model.pkl"
        ckpt.write_bytes(pickle.dumps(clf))
        run.log_artifact(ckpt, kind="checkpoint")
    print(f"{args.model} seed={args.seed} done")


if __name__ == "__main__":
    main()
