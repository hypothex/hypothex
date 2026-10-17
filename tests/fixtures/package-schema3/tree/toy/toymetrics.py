from hypothex.metrics import MetricResult


def accuracy(examples):
    per = {e.id: {"correct": e.prediction == e.reference} for e in examples}
    value = sum(v["correct"] for v in per.values()) / max(len(per), 1)
    return MetricResult(values={"value": value}, per_example=per)


def broken(examples):
    raise RuntimeError("boom")
