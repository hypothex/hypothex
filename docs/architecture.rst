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

Atomic writes use a byte-bounded temporary filename, including for long Unicode
destination names, and new files follow the process umask like appended files.

``hx reindex`` rebuilds the index from run folders on disk. Because the index is
disposable, Hypothex stores a schema version and rebuilds it automatically when
that version changes.

A rebuild is atomic. It writes every run into a unique ``index.db.tmp-*`` directory first; then one
write transaction on ``index.db`` re-reads the runs that changed meanwhile and
replaces every table. Other processes (``hx serve``, the GPU scheduler, CLI
commands) read the old index until that commit and the new one after it, never
a part of it, and writes made during the rebuild are kept. One rebuild runs at a
time where advisory file locks are available. Otherwise, independent staging
directories and retained change markers preserve writes across overlapping rebuilds.
A rebuild does not read ``metrics.jsonl``: a run's downsampled points are
indexed the first time they are asked for, so rebuild time excludes reading
metric histories.

A run's metric curve is indexed as at most 1,000 points per metric, thinned with
LTTB (largest triangle three buckets), which keeps the peaks: a one-step spike in
the loss stays on the curve. Points indexed by an older Hypothex keep their old
thinning until the run is indexed again (``hx reindex``). View curves further
limit each series to 500 points; the metrics API accepts a separate ``max_points`` limit.

An ended run's points are indexed from its whole file. A queued, running or lost
run may still be writing its file, so the index (and every view) reads it one line
at a time into a bounded copy: at most 1,000 points per name, with the first, last,
lowest and highest kept and the rest chosen by LTTB. At most the first 256 distinct
names in the file are retained; rows of further names are skipped, with warnings
remembered for the most recent 1,024 runs per store. Lines over 64 KiB or containing
invalid UTF-8 are skipped. Repeated points share their metric-name string, so long
names consume memory once per name rather than once per buffered point.
Exact reads of state files have no byte or name cap and reject invalid UTF-8.
Every end path (the local supervisor, a SLURM end, ``hx stop`` of a run whose
supervisor is gone, the hub's mirror of a host's end) indexes the run again from
its whole file.
The local supervisor publishes terminal status before installing that exact
history, so a concurrent rebuild cannot leave the earlier live copy in place.
Deferred index hydration installs a read only while its pending marker and run
status still match. A read started before a run finished cannot overwrite its
newer terminal history, including when an intervening rebuild recreated the marker.

Every write of indexed data adds 1 to the index *generation* (a ``meta`` row
written in the same transaction). Setting a mirror cursor or marking scores stale
does not count. ``hypothex.core.index.index_generation(ctx)`` reads it, so a cache
of anything built from the index can use the generation as its key. Leaderboards
do this: ``hypothex.core.leaderboard.cached_leaderboard`` keeps up to
``BOARD_CACHE_SIZE`` boards, keyed by the database device and inode plus generation,
the project, the task, the config, the metric versions, and a ``variant`` for
anything else the board depends on. File identity prevents a replaced database
from reusing a board at the same generation. ``get_leaderboard``, ``list_tasks``,
the overview, view panels, and sweep tables all use it.

.. code-block:: python

   from hypothex.core.leaderboard import build_leaderboard, cached_leaderboard

   board = cached_leaderboard(
       ctx, "toy", "toy-acc", config,
       lambda: build_leaderboard("toy", "toy-acc", config, runs, scores),
       variant=("examples", False),
   )

A write to any task (a live metric too) starts a new generation, so every cached
board is built again on its next read.

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
lossless. A page that has just loaded its data subscribes with ``"latest"`` (no
replay), and a client may cap the replay with ``max_replay``: past the cap it gets one
``reset`` message and reloads instead of reading the whole log.

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

``POST /api/v1/sweeps`` is the exception: it keeps no receipt. A retry with the same
``command_id`` finds the sweep that id made and starts only its missing runs, also
after the hub stopped in the middle of the launch. Each sweep run has its own
command id on the host; when the host answers that this id was interrupted, the
hub tries the run's next id, with at most 4 ids per run (``MAX_RUN_ATTEMPTS``).

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

``hx stop`` writes a ``stop_requested`` marker into the run folder, then sends
``SIGTERM`` to the command's process group and ``SIGKILL`` 10 s later. The
supervisor also checks for the marker every 0.5 s (``STOP_POLL_SECONDS``) while the
command runs, so a command that started just after the stop is stopped too.

Local-only API
--------------

``hx serve`` binds ``127.0.0.1`` by default. The ``Host`` header must be ``127.0.0.1``, ``localhost``, ``[::1]`` (any port),
or the ``--host`` address when it is not a wildcard such as ``0.0.0.0``;
anything else gets ``400``. This blocks DNS-rebinding attacks, where a web page
makes its own host name resolve to ``127.0.0.1``. A ``POST`` or WebSocket
handshake whose ``Origin`` is not the server's own (the request's host and port)
gets ``403``, so a web page, even one on another local port, cannot start runs
through the user's browser. A ``POST`` must also send JSON (or an
``X-Hypothex-Client`` header), else ``415``. Clients that send no ``Origin`` (the
CLI, MCP clients, ``curl -H 'content-type: application/json'``) are not affected.

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
paired-test pools. Per-seed and per-example averaging keeps finite means
representable when their intermediate sums exceed floating-point range.
Runs without a seed remain separate samples. Costs and run
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
Both delayed checkout and staging cleanup check that the project is local before
using recorded repository paths; a mirrored project cannot reuse a coincidentally
matching local path.

Mirrored run details show host-qualified run, repository, working-directory
and captured-file paths. The hub's local mirror paths are used internally for
reads, while displayed paths identify the files on the original host.
Remote task snapshots retain dataset paths as configured on their host. They do
not expose locally resolved dataset paths or splits, even when the same repository
path happens to exist on the hub.


Run-id reservations
-------------------

Preparation draws a new run id when the selected run directory or execution
checkout is already claimed. A pinned run reserves its execution directory
exclusively when it starts (before submission for SLURM). A later collision fails
that run without executing in or deleting the competing checkout. Cleanup removes
only a checkout whose successful creation this run recorded.
