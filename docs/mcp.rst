MCP server
==========

Hypothex has an MCP server, so an agent can find tasks, launch runs and sweeps, and
read results without the shell. See :doc:`agents` for how to connect one.

Start it
--------

.. code-block:: bash

   hx mcp                                   # stdio, for Claude Code, Codex, ...
   claude mcp add hypothex -- hx mcp        # register it with Claude Code

``hx serve`` also serves it over streamable HTTP at ``http://127.0.0.1:7777/mcp/``.

The host tools (``list_hosts``, launches with ``host``, sweeps on a host,
``pull_artifact``) call the hub at ``HYPOTHEX_HUB_URL`` (default
``http://127.0.0.1:7777``), so ``hx serve`` must run on the hub. They send
``HYPOTHEX_HUB_TOKEN`` when it is set; otherwise local stdio clients may discover
the matching loopback server's credential from its private record. The MCP server
inside ``hx serve`` forwards the caller's validated credential. Missing or invalid
caller credentials never fall back to the server's root token.
Hub calls do not follow redirects or inherit proxy/TLS environment settings.

Both ``/mcp`` and ``/mcp/`` remain authenticated. For a default local server, use
``hx token`` with the same Hypothex home to retrieve the bearer credential.

An expected error (a bad argument, an unknown run, a host that is not connected) comes
back as a tool error with a readable message.

Tools
-----

Discover:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Tool
     - What it does
   * - ``list_projects()``
     - Projects with their repo paths and task names.
   * - ``list_tasks(project=None)``
     - Tasks: dataset and version, metric versions, primary metric, run count, best.
   * - ``get_task(task, project=None)``
     - A task's dataset, metrics, stages, and repo.
   * - ``get_leaderboard(task, project=None)``
     - Seed groups ranked by the primary metric (mean, std, n, cost).
   * - ``list_runs(project=None, task=None, status=None, tag=None, limit=50)``
     - Runs, newest first.
   * - ``get_run(run_id)``
     - Everything about a run: record, scores, notes, children, and file paths.
   * - ``compare_runs(run_ids)``
     - Config fields and scores that differ.
   * - ``get_predictions(run_id, metric=None, failures_only=False, offset=0, limit=50)``
     - Predictions with references and per-example scores.

Run:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Tool
     - What it does
   * - ``launch_run(repo, hypothesis, task=None, stage=None, command=None, seed=None,
       params=None, template_vars=None, tags=None, agent="mcp", host=None, gpus=0,
       queue=False)``
     - Start a run in the background. ``host`` runs it on that host with the host's
       checkout (the commit and uncommitted diff of ``repo`` are sent along).
       ``gpus`` and ``queue=True`` wait for free GPUs there. A hypothesis is required.
   * - ``rerun(run_id, agent="mcp")``
     - Rerun with the same command, commit, config, and seed.
   * - ``reinfer(run_id, checkpoint=None, agent="mcp")``
     - Run the ``infer`` stage again with the run's checkpoint.
   * - ``reevaluate(run_id=None, task=None, project=None, metric=None, force=False)``
     - Score saved predictions again with the current metric versions.
   * - ``stop_run(run_id)``
     - Stop a queued or running run (``scancel`` on SLURM).
   * - ``add_note(run_id, text, author="agent")``
     - Append a Markdown note.
   * - ``tag_run(run_id, add=None, remove=None)``
     - Add or remove tags.

Hosts and sweeps:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Tool
     - What it does
   * - ``list_hosts()``
     - Hosts the hub knows, ``local`` first: state, GPUs (and the run or outside
       process that holds each), queue length, SLURM pending/running, cost today.
   * - ``launch_sweep(project, command, hypothesis, grid, seeds, task=None, host=None,
       random=None, ranges=None, gpus=0, queue=False, agent="mcp", repo=None)``
     - Start a sweep. ``grid`` maps each name to its values, e.g.
       ``{"lr": ["1e-4", "3e-4"]}``. ``ranges`` maps a name to ``"low:high[:log]"``,
       sampled ``random`` times. The command must use every name as ``{name}``.
       With ``host``, the commit and uncommitted diff of the client's checkout
       (``repo``, default the project's registered checkout) are sent along, as
       ``hx sweep --host`` does. Answers the sweep summary.
   * - ``get_sweep(project, sweep_id)``
     - Progress counts, parameters x primary metric cells, best cell, cost.
   * - ``cancel_sweep(project, sweep_id)``
     - Stop the sweep's queued runs; started runs keep going.
   * - ``extend_sweep(project, sweep_id, seeds, agent="mcp")``
     - Add runs for every combination x the new seeds.
   * - ``pull_artifact(run_id, artifact="checkpoint")``
     - Copy one big file of a remote run to the hub: an artifact kind, an artifact
       path, or a run-folder path. Answers ``{local_path}``.

Views:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Tool
     - What it does
   * - ``list_views(task, project=None)``
     - A task's views.
   * - ``get_view(task, name, project=None)``
     - One view: its YAML text and the resolved view.
   * - ``add_view(task, name, yaml_text, project=None)``
     - Validate and save a view. When it is not valid, nothing is saved and
       ``ok: false`` comes back with ``issues``.
   * - ``query_view(task, name, project=None)``
     - A saved view's panels as rows.

Example
-------

An agent that starts a sweep on a GPU host calls:

.. code-block:: json

   {
     "tool": "launch_sweep",
     "arguments": {
       "project": "toy-classifier",
       "task": "toy-test",
       "host": "gpu-box",
       "hypothesis": "a forest beats logreg on this split",
       "grid": {"model": ["logreg", "rf"]},
       "seeds": [1, 2, 3],
       "command": ["python", "train_eval.py", "--model", "{model}", "--seed", "{seed}"],
       "gpus": 1,
       "queue": true,
       "agent": "claude"
     }
   }

Then it follows the sweep with ``get_sweep(project="toy-classifier", sweep_id=...)``.
