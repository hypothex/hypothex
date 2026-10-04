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
``--wait`` blocks until the run ends.

.. code-block:: bash

   hx launch --host gpu-box --gpus 2 --queue -t TASK -H WHY --json -- python train.py
   hx launch --host cluster --gpus 4 --time 04:00:00 --partition gpu --account my-lab \
       -t TASK -H WHY --json -- python train.py

Start a run on a remote host. ``--gpus N`` asks for GPUs, ``--queue`` waits for them
(:doc:`gpus`). ``--partition``, ``--time``, and ``--account`` override the SLURM host's
defaults (:doc:`slurm`). See :doc:`remote`.

.. code-block:: bash

   hx rerun RUN_ID --json

Rerun with the same command, commit, config, and seed. If the repo has moved on
(new commit or different uncommitted diff), the rerun uses a fresh git worktree at
the recorded commit with the saved diff applied; ``{repo}``, dataset paths, and the
captured environment then point into that worktree, and the run is scored with its
metric code. When the run ends, the worktree is removed unless the run left files in
it (outputs, checkpoints). If the repo itself moved and the project was re-registered
at the new path, the working directory is mapped onto the new location.

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

Remote hosts
------------

.. code-block:: bash

   hx hosts add gpu-box --ssh gpu-box --usd-per-gpu-hour 2.10 --json
   hx hosts add cluster --ssh cluster-login --slurm --partition gpu --time 08:00:00 --json
   hx hosts map PROJECT gpu-box /home/me/code/project --json

Add a host (``--ssh ALIAS`` or ``--url URL``; ``--slurm``, ``--partition``,
``--account``, ``--time``, ``--gpus``, ``--remote-home``, ``--usd-per-gpu-hour``), and
say where a project's checkout is on it.

.. code-block:: bash

   hx hosts list --json
   hx hosts status [HOST] --json
   hx hosts connect HOST --json
   hx hosts disconnect HOST --json
   hx hosts upgrade HOST --json
   hx hosts rm HOST --json

List the hosts in ``environments.yaml``; show live state, GPUs, queue, SLURM jobs, and
cost today; reconnect or stop watching a host; install this Hypothex version on it;
remove it. See :doc:`remote`.

.. code-block:: bash

   hx pull RUN_ID --artifact checkpoint --json

Copy a big file of a remote run to the hub (``--artifact``: a kind, an artifact path,
or a run-folder path; default ``checkpoint``).

.. code-block:: bash

   hx service install --kind ssh --json
   hx service uninstall --json

On a host: write a systemd user unit or launchd agent for its env server, and print
how to enable it.

Sweeps
------

.. code-block:: bash

   hx sweep -t TASK -H WHY --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 3 \
       --host gpu-box --gpus 1 --queue --json -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'

Start a sweep: every grid combination x seed (``--random N`` with
``--param name=low:high[:log]`` for random search).

.. code-block:: bash

   hx sweeps [-p PROJECT] --json
   hx sweep show SWEEP_ID --json
   hx sweep extend SWEEP_ID --seeds 4,5 --json
   hx sweep cancel SWEEP_ID --json

List sweeps; show one (progress, parameters x primary metric, best cell, cost); add
seeds; stop its queued runs. See :doc:`sweeps`.

Servers
-------

.. code-block:: bash

   hx serve

Serve the HTTP/WebSocket API on ``127.0.0.1:7777``, and the UI at
``http://127.0.0.1:7777/`` when the package contains a UI build
(``src/hypothex/ui_dist``; ``cd ui && bun run build`` makes one).

``--port 0`` picks a free port. ``--kind ssh|slurm`` runs it as a host's env server
(GPU queue, or SLURM submission); the kind is saved for the next start. An env server
always requires a bearer token unless ``--no-auth`` (test hosts only).

``--host`` other than a loopback address (``127.0.0.1``, ``::1``, ``localhost``)
is refused unless ``HYPOTHEX_SERVE_TOKEN`` is set, because the API starts
arbitrary commands. With the token set, every request except the environment
descriptor needs ``Authorization: Bearer <token>``:

.. code-block:: bash

   HYPOTHEX_SERVE_TOKEN=$(openssl rand -hex 24) hx serve --host 0.0.0.0

The CLI and ``hx mcp`` reach the hub at ``HYPOTHEX_HUB_URL`` (default
``http://127.0.0.1:7777``) and send ``HYPOTHEX_HUB_TOKEN`` when it is set. Without
it, for a hub on this machine they read the token from the hub's own
``<home>/serve/server.json`` (owner-only). The MCP server that ``hx serve`` mounts
uses the server's token:

.. code-block:: bash

   HYPOTHEX_HUB_URL=http://hub.example:7777 HYPOTHEX_HUB_TOKEN=... hx hosts status

.. code-block:: bash

   hx mcp

Run the MCP server over stdio, for Claude Code, Codex, and other MCP clients.

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Meaning
   * - ``HYPOTHEX_HOME``
     - The Hypothex home (same as ``--home``; default ``~/.hypothex``).
   * - ``HYPOTHEX_AGENT``
     - Record runs as ``agent:<name>``; a hypothesis is then required.
   * - ``HYPOTHEX_HUB_URL``
     - Where the CLI and ``hx mcp`` find the hub (default ``http://127.0.0.1:7777``).
   * - ``HYPOTHEX_HUB_TOKEN``
     - The bearer token they send to the hub.
   * - ``HYPOTHEX_SERVE_TOKEN``
     - The bearer token ``hx serve`` requires.
   * - ``HYPOTHEX_SSH``, ``HYPOTHEX_SCP``
     - The ``ssh`` and ``scp`` programs to use (default ``ssh`` and ``scp``).
   * - ``HYPOTHEX_FAKE_GPUS``
     - A JSON file of fake GPUs instead of ``nvidia-smi`` (tests and demos).

A run's command gets ``HYPOTHEX_RUN_DIR``, ``HYPOTHEX_RUN_ID``, ``HYPOTHEX_PROJECT``,
``HYPOTHEX_SEED`` (when it has a seed), and ``CUDA_VISIBLE_DEVICES`` (when it holds
GPUs).
