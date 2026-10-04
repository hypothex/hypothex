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

Seed identity and repeated runs
-------------------------------

A seed group includes the configuration hash, commit and the recorded dirty-diff
hash. Launch captures the first eight SHA-256 hex digits of ``git.diff``; if the
diff exceeds the capture limit, the captured diff stat is hashed instead. The
stat fallback identifies a summary, not exact content, and cannot support an
exact rerun. Dirty group ids include all eight digits so distinct stored hashes
cannot overwrite each other's paired-test data. Legacy dirty runs without a
hash retain the ``+dirty`` suffix.

Repeated runs of one seed are averaged before computing seed statistics and
paired-test pools. Runs without a seed remain separate samples. Costs and run
membership still include every run. ``metric_drift`` lists selected metric versions
whose stored scores contain differing source hashes; reading a leaderboard does
not execute repository code. ``within_noise_of_best`` is determined by
the comparison p-value (``p >= 0.05``), or is unknown when no p-value is available.

Queue tickets and remote paths
------------------------------

Queued runs retain a stable ticket in ``run.yaml``. Run-list and run-detail
responses replace the ticket with its current one-based position across the
entire environment queue, including when a response filters or limits runs.
Batch cancellation takes one scheduler lock and does not rewrite the tickets
of later runs.

Pinned queued and SLURM runs use a staging checkout even when the requested
revision initially matches the project working copy. Moving the working copy
while the job waits therefore cannot change its recorded code. Each executing
run still receives its own checkout.

Mirrored run details show host-qualified run, repository, working-directory
and captured-file paths. The hub's local mirror paths are used internally for
reads, while displayed paths identify the files on the original host.
