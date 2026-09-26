Architecture
============

Files first
-----------

Files are the source of truth; the SQLite index (``~/.hypothex/index.db``) is a
disposable, rebuildable cache. Each run lives at
``<store>/<project>/runs/<run_id>/`` and holds ``run.yaml`` (all facts about the
run), ``config.yaml``, append-only ``metrics.jsonl`` and ``scores.jsonl``,
``predictions/``, ``logs/``, a captured ``env/``, ``git.diff``, and ``notes.md``.
``git.diff`` holds the raw bytes of ``git diff HEAD --binary``, so files in any
encoding reproduce exactly. The recorded ``origin`` URL has any user name,
password, or token removed.
Every ``run.yaml`` write is atomic (write to a temp file, then ``os.replace``) and
happens under a per-run lock. Old scores are never overwritten or deleted;
re-evaluation only appends.

``hx reindex`` rebuilds the index from run folders on disk. Because the index is
disposable, Hypothex stores a schema version and rebuilds it automatically when
that version changes.

Event log and replay
---------------------

Each environment (a host running ``hx serve``) keeps an append-only event log with
a monotonically increasing ``sequence``: ``run.created``, ``run.started``,
``run.log_chunk``, ``run.metric``, ``run.score_added``, ``run.finished``,
``run.failed``, ``run.killed``, ``run.lost``, and so on. Run folders are the
result of applying these events; the event log is the ordered change feed that
streaming and replay use.

Phase 1a simplification: every state change is written synchronously, under the
per-run file lock, in the order run folder -> event -> index. A reactor model can
replace this later without changing the file layout or the event schema.

Clients subscribe with ``after_sequence=<last seen>``: the server replays missed
events, then streams live ones, and the client drops anything it has already
seen by sequence. This makes reconnecting after a dropped connection safe and
lossless.

Idempotent commands
--------------------

Every mutating call (``launch``, ``rerun``, ``stop``, ...) carries a
client-generated ``command_id``. The server stores a receipt for that id in the
same transaction as the events it produces; a repeated ``command_id`` returns the
first result instead of doing the work twice. This makes a double-clicked
"Rerun" (or a retried agent call) start exactly one run.

Supervisors and repair
------------------------

Each run is started under a supervisor process that tracks its exit and writes
the final status. On startup, an environment reconciles any run it last recorded
as ``running``: if the process is still alive, it is left running; if it exited
with a recorded exit code, it is finished or failed; otherwise it is marked
``lost``. ``hx repair`` triggers this reconciliation on demand, ``hx serve``
repeats it every 30 seconds, and ``hx launch --wait`` checks its own run every
5 seconds. A queued run is judged by its detached supervisor's pid
(``supervisor.pid``), not by the process that launched it, so a supervisor that
dies before starting the command is marked ``lost`` after a 60 second grace
period even while the launching server is still up.

Local-only API
--------------

Phase 1a has no authentication, so ``hx serve`` only answers local requests.
The ``Host`` header must be ``127.0.0.1``, ``localhost``, ``[::1]`` (any port),
or the ``--host`` address when it is not a wildcard such as ``0.0.0.0``;
anything else gets ``400``. This blocks DNS-rebinding attacks, where a web page
makes its own host name resolve to ``127.0.0.1``. A ``POST`` or WebSocket
handshake whose ``Origin`` is not one of those hosts gets ``403``, so a web page
cannot start runs through the user's browser. Clients that send no ``Origin``
(the CLI, MCP clients, ``curl``) are not affected.

.. code-block:: bash

   curl -H 'Host: attacker.example' http://127.0.0.1:7777/api/v1/runs   # 400

Phase 2
-------

Phase 1a runs everything on one machine. Phase 2 adds env servers per machine
(SSH boxes, SLURM login nodes) alongside the hub: each environment owns its own
runs, event log, and supervisors, so a run keeps going and keeps being recorded
even if the hub machine sleeps or the network drops. The hub reaches an
environment over SSH tunnels or a direct URL, but the environment's identity
(``environment_id``) is stable regardless of the route.
