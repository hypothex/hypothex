"""Metrics for the toy task. Bump the version in hypothex.yaml when you change one."""

from sklearn.metrics import f1_score

from hypothex import Example, MetricResult


def accuracy(examples: list[Example]) -> MetricResult:
    """Fraction of exact matches, with per-example correctness."""
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    return MetricResult(
        values={"value": sum(v["correct"] for v in per.values()) / len(per)}, per_example=per
    )


def macro_f1(examples: list[Example]) -> float:
    """Macro-averaged F1."""
    return float(
        f1_score([e.reference for e in examples], [e.prediction for e in examples], average="macro")
    )
