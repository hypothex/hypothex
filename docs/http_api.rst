HTTP API
========

``hx serve`` serves a JSON API under ``/api/v1``, a WebSocket event stream, and the MCP
server. The OpenAPI docs are at ``http://127.0.0.1:7777/api/docs`` (schema:
``/api/openapi.json``). This page lists the routes. See :doc:`security` for the access
rules.

Every server requires a bearer token by default. Send it in the Authorization
header; OpenAPI, API data, files and MCP remain protected. Only GET/HEAD of the
exact public identity descriptor and installed UI resources/navigation are public.
Run ``hx token`` locally with the server's Hypothex home to retrieve its credential.

``POST /api/v1/auth/ws-ticket`` requires that bearer and returns
``{"ticket": "...", "expires_in": 30}`` with ``Cache-Control: no-store``. Tickets
are single-use and server-local; at most 256 unexpired tickets are outstanding,
after which issuance returns ``429``. Explicit no-auth servers return
``{"ticket": null, "expires_in": 0}``.

Conventions
-----------

- Errors are JSON: ``{"error": "...", "type": "..."}``. ``400`` for a bad request,
  ``401`` for a missing or wrong bearer token, ``404`` for an unknown run, project, or
  file, ``409`` for an interrupted command, ``413`` for a file larger than
  ``max_bytes``, ``415`` for a ``POST`` without JSON, ``422`` for a body that does
  not match the schema, and ``503`` when a host is not connected (or no configured
  host serves the run). A ``422`` also has FastAPI's ``detail`` list, without the
  ``input`` values, so the answer never echoes the body back.
- Answers of 2 KiB or more are gzipped when the client sends
  ``Accept-Encoding: gzip`` (browsers, ``httpx`` and ``curl --compressed`` do). Run
  files (``application/octet-stream``) are sent as they are.
- A ``POST`` needs a JSON body (``Content-Type: application/json``, ``{}`` when
  there is nothing to send) or an ``X-Hypothex-Client`` header; else ``415``.
- Every ``POST`` body takes an optional ``command_id``. A repeated ``command_id``
  returns the first result and does the work only once. ``created_by`` names the
  author (``agent:<name>`` for agents; such launches need a ``hypothesis``).

.. code-block:: bash

   printf 'Authorization: Bearer %s\n' "$(hx token)" | \
       curl -s -H @- http://127.0.0.1:7777/api/v1/hosts | jq '.[].name'
   printf 'Authorization: Bearer %s\n' "$(hx token)" | \
       curl -s -H @- -X POST http://127.0.0.1:7777/api/v1/hosts/gpu-box/connect \
       -H 'content-type: application/json' -d '{}'

Hosts (hub)
-----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Route
     - Body and answer
   * - ``GET /api/v1/hosts``
     - One row per host, the hub first (``name`` and ``kind`` ``"local"``):
       ``{name, kind, state, gpus, queue, slurm, cost_today_usd, usd_per_gpu_hour,
       projects, stale_banner_hours}``. ``state`` is a host state
       ``{name, kind, state, since, message, environment_id, hx_version,
       last_sequence, local_port}``. ``slurm`` is
       ``{pending, running, comment_accounting}`` for a SLURM host, else ``null``.
   * - ``POST /api/v1/hosts/reload``
     - ``{command_id?}``. Reads ``environments.yaml`` again and answers the host
       rows. ``hx hosts map`` and ``rm`` call it; ``hx hosts add`` calls ``connect``, which
       also re-reads the file.
   * - ``POST /api/v1/hosts/{host}/connect``
     - ``{command_id?}``. Answers the host state.
   * - ``POST /api/v1/hosts/{host}/disconnect``
     - ``{command_id?}``. Answers the host state (``disabled``).
   * - ``POST /api/v1/hosts/{host}/runs``
     - Launch on a host. The launch fields (``task``, ``stage``, ``command``,
       ``hypothesis``, ``seed``, ``tags``, ``params``, ``vars``) plus ``gpus``,
       ``queue``, ``slurm`` (``{partition, account, time, gpus, extra}``),
       ``project``, ``commit``, and ``diff``. Answers the run record. On a host that is
       not a SLURM host, ``slurm`` may hold only ``gpus`` (it is ignored there).

For a host launch, give the project by name. Without ``commit``, the hub pins its own
checkout's ``HEAD`` and sends its uncommitted diff. With ``commit``, the body's
``diff`` is used (none for a clean run).

.. code-block:: bash

   printf 'Authorization: Bearer %s\n' "$(hx token)" | \
       curl -s -H @- -X POST http://127.0.0.1:7777/api/v1/hosts/gpu-box/runs \
       -H 'content-type: application/json' -d '{
         "project": "toy-classifier", "task": "toy-test", "hypothesis": "rf on the GPU box",
         "command": ["python", "train_eval.py", "--model", "rf", "--seed", "{seed}"],
         "seed": 1, "gpus": 1, "queue": true, "created_by": "human"}'

Runs
----

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Route
     - Body and answer
   * - ``GET /api/v1/runs``
     - Query: ``project``, ``task``, ``status``, ``tag``, ``environment_id``,
       ``archived``, ``limit`` (default 200), and the keyset cursor
       ``before_created_at`` + ``before_run_id`` (both or neither: the ``created_at``
       and ``run_id`` of the last row of the previous page). Answers run records,
       newest first, each with ``host_state`` as in ``GET /api/v1/runs/{id}``.
   * - ``POST /api/v1/runs``
     - Launch here: ``repo`` plus the launch fields, ``gpus``, ``queue``. Answers the
       run record.
   * - ``GET /api/v1/runs/{id}``
     - Everything about a run, plus ``host_state`` (the state name of its host,
       such as ``"connected"``; ``null`` for a run of the hub). ``metric_names``
       is sorted. For queued, running and lost runs it reflects the current
       ``metrics.jsonl``, including names not yet indexed: the first 256 distinct
       names from valid rows, skipping lines over 64 KiB and invalid UTF-8,
       matching live curve reads. Name lookup retains no histories and stops
       at the name cap. Unchanged files reuse a thread-safe per-store cache of
       at most 32 results and 4 MiB of UTF-8 name bytes; oversized results are
       returned uncached. Device, inode, size, mtime and ctime changes invalidate
       a result. Appended or edited files are rescanned, so this cache removes
       repeated unchanged-file work without delaying newly logged names.
       Finished, failed and killed runs use indexed names,
       without a name cap or another history scan when already indexed.
   * - ``GET /api/v1/runs/{id}/metrics``, ``/traces``, ``/traces/{example_id}``,
       ``/logs``, ``/predictions``
     - The run's metrics (``names``, repeatable, keeps only those metrics;
       ``max_points`` >= 2 thins each series to that many points with LTTB, keeping
       its ends and peaks; without them, every indexed point), traces, log tail
       (``stream``, ``offset``), and predictions (``offset``, ``limit``, ``metric``,
       ``failures_only``, ``field``).
   * - ``POST /api/v1/runs/{id}/stop``
     - ``{only_queued?}``. Stops the run (``scancel`` on SLURM).
   * - ``POST /api/v1/runs/{id}/rerun``, ``/reinfer``, ``/reeval``
     - Rerun, re-infer (``{checkpoint?}``), re-evaluate (``{metric?, force?}``).
   * - ``POST /api/v1/runs/{id}/tags``, ``/star``, ``/archive``, ``/notes``
     - ``{add, remove}``, ``{on}``, ``{on}``, ``{text, author}``.
   * - ``POST /api/v1/runs/{id}/pull``
     - ``{artifact}`` (default ``checkpoint``): an artifact kind, an artifact path, or
       a run-folder path. Copies the file from the run's host and answers
       ``{local_path}``. ``400`` when the destination name starts with ``.hx-``.

The run actions keep their routes for remote runs: the hub sends them to the run's
host with the same ``command_id``.

Sweeps
------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Route
     - Body and answer
   * - ``POST /api/v1/sweeps``
     - ``{project, task?, host?, grid, random?, seeds, command, hypothesis, gpus?,
       queue?, commit?, diff?, command_id?}``. ``grid`` is a list of
       ``{name, values}`` or ``{name, low, high, log}``. The sweep pins its code in
       ``spec.commit`` and ``spec.diff``: the body's ``commit`` (with its ``diff``),
       else the hub checkout's ``HEAD`` and uncommitted diff. A repeated
       ``command_id`` resumes the same sweep and issues only its missing runs, also
       after the hub stopped mid-launch. Answers the sweep summary.
   * - ``GET /api/v1/sweeps/{id}``
     - The summary of a sweep in any project.
   * - ``GET /api/v1/sweeps/{project}/{id}``
     - The summary.
   * - ``GET /api/v1/projects/{project}/sweeps``
     - ``[{id, created_at, n_runs, best}]``.
   * - ``POST /api/v1/sweeps/{project}/{id}/cancel_queued``
     - ``{command_id?}``. Stops the queued runs (``killed``) and answers the summary.
   * - ``POST /api/v1/sweeps/{project}/{id}/extend``
     - ``{seeds, command_id?}``. Adds runs for every combination and new seed, at the
       sweep's ``commit`` and ``diff`` (not the checkout as it is now), and answers the
       summary.

The summary is ``{spec, counts, cells, best, headline, total_usd, run_ids, tag}``. See
:doc:`sweeps`.

.. code-block:: bash

   printf 'Authorization: Bearer %s\n' "$(hx token)" | \
       curl -s -H @- -X POST http://127.0.0.1:7777/api/v1/sweeps \
       -H 'content-type: application/json' -d '{
         "project": "toy-classifier", "task": "toy-test", "host": "gpu-box",
         "grid": [{"name": "model", "values": ["logreg", "rf"]}], "seeds": [1, 2, 3],
         "command": ["python", "train_eval.py", "--model", "{model}", "--seed", "{seed}"],
         "hypothesis": "model choice", "gpus": 1, "queue": true}'

Env server routes
-----------------

Each env server (``hx serve --kind ssh|slurm`` on a host) serves the routes above for
its own runs, plus these. The hub calls them through the tunnel with the env server's
bearer token.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Route
     - Answer
   * - ``GET /.well-known/hypothex/environment``
     - The descriptor: ``environment_id``, ``label``, ``kind``, ``os``, ``arch``,
       ``hostname``, ``hx_version``, ``protocol_version``, ``gpus``, ``capabilities``.
       Open without a token, but then (on a server that has one) it names only
       ``environment_id``, ``protocol_version`` and ``hx_version``.
   * - ``GET /api/v1/gpus``
     - ``[{index, name, util, mem_used_mb, mem_total_mb, external, run_id}]``.
   * - ``GET /api/v1/queue``
     - ``[{run_id, position, gpus_requested}]``.
   * - ``GET /api/v1/slurm``
     - ``{comment_accounting}``: ``true``, ``false``, or ``null`` (not a SLURM server).
   * - ``GET /api/v1/runs/{id}/files/{path}``
     - The file's bytes (query ``max_bytes``, ``tail``), or a listing for a folder.
       ``404`` for a missing file or any path in the reserved ``.hx/`` folder,
       ``413`` for a file larger than ``max_bytes``.
   * - ``GET /api/v1/projects/{project}/entry``
     - The host's project entry (the hub copies a project that is only on the host).

Other routes
------------

- ``GET /api/v1/overview`` (``since``): the Overview, with ``cost_usd`` and
  ``cost_today_usd``.
- ``GET /api/v1/projects``, ``GET /api/v1/tasks``, ``GET /api/v1/tasks/{project}/{task}``,
  ``GET /api/v1/tasks/{project}/{task}/leaderboard`` (rows have ``cost``),
  ``POST /api/v1/tasks/{project}/{task}/reeval``, ``GET .../kind``, and the views
  routes under ``/api/v1/tasks/{project}/{task}/views``.
- The task ``reeval`` scores the hub's own runs on the hub and sends each mirrored
  run's re-evaluation to its host (command id ``<command_id>:<run_id>``), waiting up
  to 600 s for each answer. A run whose host is not connected or no longer
  configured is listed in ``skipped`` with the reason.
- ``GET /api/v1/compare?ids=a,b``, ``GET /api/v1/compare/examples?a=&b=&metric=``,
  ``GET /api/v1/datasets/check``.
- ``/mcp/``: the MCP server over streamable HTTP (see :doc:`mcp`).

Event stream
------------

``/api/v1/ws`` is a WebSocket. Browsers offer protocols ``hypothex.v1`` and
``hx-ticket.<ticket>`` using a fresh ticket from the endpoint above; the server
selects only ``hypothex.v1``. No-auth browsers offer only the fixed protocol.
Nonbrowser clients may still use a bearer Authorization header. Credentials never
belong in a URL. Host/Origin checks precede ticket consumption, and an invalid
supplied bearer cannot fall back to a ticket.

Send ``{"type": "subscribe", "after_sequence": N}``
first. The server sends every event after ``N`` as ``{"type": "event", "event":
{...}}``, then ``{"type": "ready", "last_sequence": M}``, then live events.

- ``"after_sequence": "latest"`` skips the replay: ``ready`` comes at once, then live
  events. Use it on a page that has just loaded its data.
- ``"max_replay": K`` (optional, ``K >= 1``) caps the replay. When more than ``K``
  events are missing, the server sends ``{"type": "reset", "last_sequence": M}``
  instead of them, then ``ready`` and live events; reload your data on ``reset``.
  Without ``max_replay`` every missing event is replayed (the hub's mirror needs them).

.. code-block:: json

   {"type": "subscribe", "after_sequence": 41, "max_replay": 5000}

On the
hub, a change to a remote run arrives as ``mirror.run_updated`` with
``{host, environment_id, original_type, remote_sequence, status, reason?}``.
