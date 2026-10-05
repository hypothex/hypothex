The project file: ``hypothex.yaml``
====================================

Every Hypothex project has one ``hypothex.yaml`` at the repository root. It declares
the project's datasets, versioned metrics, tasks (a dataset plus the metrics that
score it), stage command templates, and the Python command used for scoring.

.. code-block:: yaml

   project: deepretro
   description: Multi-step retrosynthesis with LLM-guided search.

   datasets:
     uspto50k:
       version: v1
       host: gpu-box-1            # where the canonical copy lives
       path: /data/uspto50k/test.jsonl
       description: USPTO-50k test split (Schneider 2016 split)
       splits: {train: /data/uspto50k/train.jsonl, test: /data/uspto50k/test.jsonl}

   metrics:
     topk:
       version: v2
       fn: deepretro.eval.metrics:topk_accuracy   # module:function in this repo
       higher_is_better: true
       unit: ""                                    # optional display unit: ms, $, tokens
       params: {k: [1, 5, 10]}
       changelog:
         v1: initial
         v2: canonicalize SMILES before matching

   tasks:
     uspto50k-topk:
       dataset: uspto50k
       split: test
       metrics: [topk]
       primary: topk/k=1           # metric/key the leaderboard sorts by (`@` is reserved for versions)

   stages:                         # command templates; {vars} are filled by hx
     train: python -m deepretro.train --config {config} --out {run_dir}/artifacts
     infer: python -m deepretro.infer --ckpt {checkpoint} --data {dataset.path} --out {run_dir}/predictions

   env:
     python: [uv, run, python]      # runs metric functions and captures the environment
     setup: uv sync                # accepted metadata; not executed by hx

Sections
--------

``datasets``
   Named datasets with a ``version`` (bump it when the data changes), the ``path`` to
   the file used by tasks, and optional named ``splits`` for overlap checks.

``metrics``
   Named metric functions, each a ``module:function`` reference (``fn``) importable
   from the project repo, with a ``version`` and a human-readable ``changelog`` keyed
   by version. Bump ``version`` whenever the metric's code changes; old scores are
   never overwritten. ``unit`` is optional and only changes display (``166 ms``,
   ``$0.55``); without it the unit comes from the name (``latency``, ``_ms`` → ``ms``;
   ``usd``, ``cost`` → ``$``; ``token`` → ``tokens``; ``seconds`` → ``s``).

``tasks``
   A task pairs a ``dataset`` (and optional ``split``) with one or more ``metrics``,
   and names the ``primary`` metric/key that the leaderboard sorts by.

``stages``
   Named command templates (``train``, ``infer``, ...) that ``hx run`` and
   ``hx launch`` select with ``--stage``. ``hx reinfer`` runs the ``infer``
   template. Scoring is built in: ``hx reeval`` evaluates saved predictions with
   the configured metric functions; it does not execute a stage command.

``env``
   ``python`` is an argument list for the project's Python, used to run metric
   functions and record the environment. When omitted, it defaults to
   ``uv run --project <repo> python``. ``setup`` is accepted and stored but is
   not executed yet; perform required setup yourself before launching runs.

Validation
----------

``hx validate`` checks the schema, that every ``fn`` imports, and that every task's
dataset and metric exist.

Template variables
-------------------

Built-in template variables, always available in stage commands and ``--config``
paths:

- ``run_id``
- ``run_dir``
- ``repo``
- ``task``
- ``seed``
- ``config``
- ``checkpoint``
- ``dataset.name``
- ``dataset.version``
- ``dataset.path``

Any other ``{name}`` used in a stage template must be supplied with ``--var
name=value``. ``hx validate`` warns about undeclared variables; ``hx launch`` (or
``hx run``) fails before creating a run if a value is missing.
