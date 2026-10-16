# Genuine schema-4 fixture

Generated from git archive `e73b8105df32a1d2488477c48e680cb5de922771`.
Old import: `src/hypothex/__init__.py`; actual SQLite schema: 4.

```sh
git archive e73b8105df32a1d2488477c48e680cb5de922771 | tar -x -C ARCHIVE
(cd ARCHIVE && uv sync --locked --all-groups)
cd ARCHIVE
uv run --no-sync python /absolute/checkout/tests/packaging/make_schema4_fixture.py   --archive ARCHIVE --output OUTPUT   --guard /absolute/checkout/tests/fakes/network.py --receipt RECEIPT
```

The generator checks pinned source bytes, old imported module path, schema, and
evaluator-issued complete scores. Manifest hashes bind frozen files, the generator,
and protected dataset/prediction/evaluator/score bytes. Relocation is restricted to
recorded structured document leaves and SQL columns; no protected byte stream may
contain a placeholder.

Strict comparison oracle:

```json
{
  "a": "a",
  "b": "b",
  "metric": "accuracy@v1",
  "field": "correct",
  "fixed": [
    "ex-3"
  ],
  "broken": [],
  "both_pass": 3,
  "both_fail": 0
}
```

Normal CI restores this data; it never fetches history or regenerates the oracle.
