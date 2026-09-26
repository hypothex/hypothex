"""Generate data/train.jsonl and data/test.jsonl for the toy task."""

import json
from pathlib import Path

from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split


def main(out_dir: Path = Path(__file__).parent / "data") -> None:
    """Write a deterministic synthetic 3-class dataset."""
    x, y = make_classification(
        n_samples=600,
        n_features=10,
        n_informative=5,
        n_classes=3,
        n_clusters_per_class=1,
        random_state=0,
    )
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.3, random_state=0, stratify=y
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, xs, ys in (("train", x_train, y_train), ("test", x_test, y_test)):
        with (out_dir / f"{name}.jsonl").open("w") as fh:
            for i, (features, label) in enumerate(zip(xs, ys, strict=True)):
                row = {
                    "id": f"{name}-{i}",
                    "x": [round(float(v), 6) for v in features],
                    "reference": int(label),
                }
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
