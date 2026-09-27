The ``hx`` CLI
===============

Every ``hx`` command supports ``--json`` for machine-readable output (a stable
``pydantic`` ``model_dump(mode="json")``); agents should always pass it.

Discover
--------

.. code-block:: bash

   hx projects --json

List every project Hypothex knows about, with its repo path and tasks.

.. code-block:: bash

   hx tasks --json

List tasks with their dataset, metric versions, primary metric, run count, and best
score.

.. code-block:: bash

   hx task show uspto50k-topk --json

Show one task: dataset, metrics, stages, and repo.

.. code-block:: bash

   hx runs --json

List runs, newest first, with filters for project, task, status, and tag.

.. code-block:: bash

   hx show RUN_ID --json

Show everything about a run: hypothesis, command, git commit, scores, and every path
(code, config, logs, predictions, checkpoint) it touches.

Run
---

.. code-block:: bash

   hx init --json

Write a starter ``hypothex.yaml`` in the current directory.

.. code-block:: bash

   hx validate --json

Check ``hypothex.yaml``, metric imports, and dataset paths.

.. code-block:: bash

   hx run -t TASK -H WHY --seed 1 --json -- python train.py --seed {seed}

Run a command in the foreground and record it.

.. code-block:: bash

   hx launch -t TASK -H WHY --stage infer --json -- python infer.py

Start a stage in the background; check progress with ``hx logs`` or ``hx show``.

.. code-block:: bash

   hx rerun RUN_ID --json

Rerun with the same command, commit, config, and seed. If the repo has moved on
(new commit or different uncommitted diff), the rerun uses a fresh git worktree at
the recorded commit with the saved diff applied. If the repo itself moved and the
project was re-registered at the new path, the working directory is mapped onto
the new location.

.. code-block:: bash

   hx stop RUN_ID --json

Stop a queued or running run.

Evaluate
--------

.. code-block:: bash

   hx reinfer RUN_ID --json

Run the ``infer`` stage again with this run's checkpoint, recording a new run whose
``parent`` is the original.

.. code-block:: bash

   hx reeval --task TASK --json

Re-score saved predictions with the current metric versions; old scores are kept and
new scores are appended.

Compare
-------

.. code-block:: bash

   hx leaderboard TASK --json

Rank seed groups of a task (mean +/- std over seeds) by the primary metric.

.. code-block:: bash

   hx compare RUN_A RUN_B --json

Show config and score differences between runs.

.. code-block:: bash

   hx examples RUN_A RUN_B --metric accuracy --json

List examples fixed or broken by run B relative to run A.

.. code-block:: bash

   hx predictions RUN_ID --failures --json

Page through a run's predictions with per-example scores.

.. code-block:: bash

   hx logs RUN_ID --follow --json

Print a run's log tail, optionally following it until the run ends.

Curate
------

.. code-block:: bash

   hx tag RUN_ID --add baseline --json

Add (or ``--remove``) a tag on a run.

.. code-block:: bash

   hx star RUN_ID --json

Star a run (``--off`` to unstar) to mark it as worth remembering.

.. code-block:: bash

   hx archive RUN_ID --json

Archive a run (``--off`` to unarchive) to hide a dead end without deleting it.

.. code-block:: bash

   hx note RUN_ID "beam width 20 helps top-10, not top-1" --json

Add a note to a run.

Views
-----

.. code-block:: bash

   hx view list TASK --json
   hx view add TASK --file view.yaml --json

List a task's dashboards, or validate and save one. See :doc:`views` for the YAML
format and the other ``hx view`` commands.

Datasets
--------

.. code-block:: bash

   hx datasets check --json

Re-fingerprint datasets used by runs and report any that have changed since the run.

.. code-block:: bash

   hx datasets overlap PROJECT DATASET --json

Count examples shared between a dataset's splits.

Maintenance
-----------

.. code-block:: bash

   hx reindex --json

Rebuild the SQLite index from run folders on disk (the index is always disposable).

.. code-block:: bash

   hx repair --json

Mark runs whose supervisor process died as ``lost``.

Servers
-------

.. code-block:: bash

   hx serve

Serve the HTTP/WebSocket API on ``127.0.0.1:7777``, and the UI at
``http://127.0.0.1:7777/`` when the package contains a UI build
(``src/hypothex/ui_dist``; ``cd ui && bun run build`` makes one).

.. code-block:: bash

   hx mcp

Run the MCP server over stdio, for Claude Code, Codex, and other MCP clients.
