# Toy classifier example

Three scikit-learn models, three seeds each, one task (`toy-test`), two metrics.

```bash
cd examples/toy-classifier
uv run python make_data.py
git init -q && git add -A && git commit -qm init   # optional, gives exact reruns

for m in logreg rf knn; do
  for s in 1 2 3; do
    uv run hx run -t toy-test -H "baseline: $m" --seed $s -- \
      python train_eval.py --model $m --seed {seed}
  done
done

uv run hx leaderboard toy-test
uv run hx show <run-id>                 # every path: code, data, results, checkpoint
uv run hx predictions <run-id> --failures
```

Change a metric? Edit `toy_metrics.py`, bump its `version` in `hypothex.yaml`, then:

```bash
uv run hx reeval --task toy-test        # re-scores saved predictions; old scores are kept
```
