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

A rebuild is atomic. It writes every run into ``index.db.tmp`` first; then one
write transaction on ``index.db`` re-reads the runs that changed meanwhile and
replaces every table. Other processes (``hx serve``, the GPU scheduler, CLI
commands) read the old index until that commit and the new one after it, never
a part of it, and writes made during the rebuild are kept. One rebuild runs at a
time. A rebuild does not read ``metrics.jsonl``: a run's downsampled points are
indexed the first time they are asked for. 20,000 runs rebuild in about 15 s.
An ended run's points are indexed from its whole file (at most 1,000 evenly spaced
points per name, the last one kept). A queued, running or lost run may still be
writing its file, so the index (and every view) reads it one line at a time into a
bounded copy: at most 1,000 points per name, the first, last, lowest and highest
kept, the rest by LTTB.

Every write of indexed data adds 1 to the index *generation* (a ``meta`` row
written in the same transaction). ``hypothex.core.index.index_generation(ctx)``
reads it, so a cache of anything built from the index (a leaderboard, a view)
can use the generation as its key:

.. code-block:: python

   from hypothex.core import queries
   from hypothex.core.index import index_generation

   key = (task, index_generation(ctx))
   if key not in cache:
       cache[key] = queries.get_leaderboard(ctx, task)
   board = cache[key]

A score append is marked in the index before the file write and cleared by the
index write, so a crash between them is repaired the next time a Hypothex
process opens the home.

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

If the server stops while a command runs, the command may already have taken
effect (a launched run outlives the server). It is never run again under that
id: a retry gets ``409`` with ``CommandInterruptedError``. Check the runs, then
send the command again with a new ``command_id``.

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

``hx serve`` binds ``127.0.0.1`` by default. The ``Host`` header must be ``127.0.0.1``, ``localhost``, ``[::1]`` (any port),
or the ``--host`` address when it is not a wildcard such as ``0.0.0.0``;
anything else gets ``400``. This blocks DNS-rebinding attacks, where a web page
makes its own host name resolve to ``127.0.0.1``. A ``POST`` or WebSocket
handshake whose ``Origin`` is not one of those hosts gets ``403``, so a web page
cannot start runs through the user's browser. Clients that send no ``Origin``
(the CLI, MCP clients, ``curl``) are not affected.

These checks are not authentication: any client that is not a browser can send
``Host: localhost``. So ``hx serve`` refuses a non-loopback ``--host`` (such as
``0.0.0.0``) unless ``HYPOTHEX_SERVE_TOKEN`` is set. With a token, every request
except ``/.well-known/hypothex/environment`` needs
``Authorization: Bearer <token>`` (``401`` otherwise; a WebSocket is closed with
code ``1008``). To reach a server on another machine without a token, keep it on
``127.0.0.1`` and use an SSH tunnel: ``ssh -L 7777:127.0.0.1:7777 HOST``.

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
