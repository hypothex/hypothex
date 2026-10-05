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

For stdio, ``HYPOTHEX_AGENT`` sets the default attribution (``mcp`` when unset).
Mutation tools with an ``agent`` argument inherit this default when it is omitted;
an explicit value overrides it for that call.

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
   * - ``get_leaderboard(task, project=None, metric=None)``
     - Seed groups ranked by the primary metric (mean, std, n, cost).
       Pin versions with ``metric=["accuracy@v1"]``. ``vs_best`` gives the
       applicable paired or Welch test; ``test_interval`` measures test-set
       uncertainty separately from variation across seeds.
   * - ``list_runs(project=None, task=None, status=None, tag=None, limit=50, full=False)``
     - Compact run summaries, newest first. Use ``full=True`` for complete records.
   * - ``get_run(run_id)``
     - Everything about a run: record, scores, notes, children, and file paths.
   * - ``compare_runs(run_ids)``
     - Config fields and scores that differ between run IDs, not group IDs.
   * - ``get_logs(run_id, stream="stderr", tail=200, offset=None)``
     - A log tail or a chunk from a byte offset. Pass the returned ``offset`` to
       continue. Host logs carry an ``untrusted_source`` marker.
   * - ``compare_examples(a, b, metric, field="correct")``
     - Paired example IDs fixed or broken by run B, and both-pass/both-fail counts.
       ``metric`` accepts ``name@version``; both runs need the requested field.
   * - ``get_predictions(run_id, metric=None, failures_only=False, offset=0, limit=50)``
     - Predictions with references and per-example scores.

Run:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Tool
     - What it does
   * - ``launch_run(repo, hypothesis, task=None, stage=None, command=None, seed=None,
       params=None, template_vars=None, tags=None, agent=None, host=None, gpus=0,
       queue=False)``
     - Start a run in the background. ``host`` runs it on that host with the host's
       checkout (the commit and uncommitted diff of ``repo`` are sent along).
       ``gpus`` and ``queue=True`` wait for free GPUs there. A hypothesis is required.
       ``template_vars`` fills command placeholders; ``params`` is recorded metadata.
   * - ``rerun(run_id, agent=None)``
     - Rerun with the same command, commit, config, and seed.
   * - ``reinfer(run_id, checkpoint=None, agent=None, vars=None)``
     - Run the ``infer`` stage again with the run's checkpoint and optional
       template-variable overrides.
   * - ``reevaluate(run_id=None, task=None, project=None, metric=None, force=False, agent=None)``
     - Score saved predictions again with the current metric versions.
   * - ``stop_run(run_id, agent=None)``
     - Stop a queued or running run (``scancel`` on SLURM).
   * - ``add_note(run_id, text, author="agent", agent=None)``
     - Append a Markdown note.
   * - ``tag_run(run_id, add=None, remove=None, agent=None)``
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
   * - ``connect_host(name, agent=None)``
     - Reconnect a configured host now. Runs already on it continue independently.
   * - ``launch_sweep(project, command, hypothesis, grid, seeds, task=None, host=None,
       random=None, ranges=None, gpus=0, queue=False, agent=None, repo=None)``
     - Start a sweep. ``grid`` maps each name to its values, e.g.
       ``{"lr": ["1e-4", "3e-4"]}``. ``ranges`` maps a name to ``"low:high[:log]"``,
       sampled ``random`` times. The command must use every name as ``{name}``.
       With ``host``, the commit and uncommitted diff of the client's checkout
       (``repo``, default the project's registered checkout) are sent along, as
       ``hx sweep --host`` does. The hub returns an accepted receipt with
       ``issuance``; use ``get_sweep`` for current progress. Direct local sweeps
       retain synchronous issuance.
   * - ``get_sweep(project, sweep_id)``
     - Current issuance, observed member counts, parameters x primary metric
       cells, best cell, cost. ``issued`` does not mean experiments have finished.
   * - ``cancel_sweep(project, sweep_id, agent=None)``
     - Stop queued runs and request cancellation of active issuance. Started
       runs keep going; in-flight launches drain before cancellation settles.
   * - ``extend_sweep(project, sweep_id, seeds, agent=None)``
     - Add runs for every combination x the new seeds, or resume missing cells
       with the reported resume seeds. Active durable issuance conflicts.
   * - ``pull_artifact(run_id, artifact="checkpoint", agent=None)``
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
