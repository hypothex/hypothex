Web UI
======

``hx serve`` serves the web UI and the API on the same port (default
``http://127.0.0.1:7777``). The UI reads everything through ``/api/v1`` and stays live
over the ``/api/v1/ws`` event stream: a new run, score, note or status change refreshes
the page you are looking at, without a reload.

.. code-block:: bash

   uv run hx serve

Screens
-------

- **Overview** (``/``): one-line status, hosts, runs by launcher, ideas, running runs,
  recent failures (with ``Open stderr``), and projects. Ideas are grouped by task, and
  each task has its own x axis, because tasks use different metrics. With hosts in
  ``environments.yaml`` (see :doc:`remote`), the headline counts running and waiting runs
  and names stale hosts, for example ``12 running, 11 waiting. dgx stale 4m``. A host
  unreachable for longer than ``stale_banner_hours`` (top level in ``environments.yaml``,
  default 24) gets a banner (``dgx unreachable 1d``); its runs stay ``stale``, never
  ``lost``. Cost today counts every run, the hub's own too.
- **Hosts** (Overview panel a): the hub itself (``local``, chip ``hub``), then one row per
  host with its state, its hx version (``≠`` when it differs from the hub's), one cell per
  GPU (agent run, human run, free, not hx), SLURM running and pending jobs, queue length,
  ``$/GPU-h`` and cost today. GPU use refreshes every 10 s. The hub reports GPUs only for a
  connected host; when a host goes stale the page keeps the cells it last saw, greyed, with
  ``as of HH:MM`` (a page opened after the host went stale has none to show).
- **Task** (``/t/<project>/<task>?view=<name>``): the task's views as tabs. ``overview``
  is the preset for the task kind; every other tab is a saved view (see :doc:`views`).
  ``+ view`` opens the view editor; ``New run`` opens the Launch dialog. The project's
  sweeps are listed under the tabs, each with its run count and best config, linking its
  Sweep page. Each leaderboard group shows its cost: dollars, GPU-h and agent time
  (``$6.51 · 11 GPU-h · 4m 10s``), with GPU and API dollars in the tooltip.
- **Launch dialog** (``New run`` on a Task page, ``Rerun sweep`` on a Sweep page): pick a
  host (the hub first, then every host with its free GPUs, queue and state; a host that is
  stale, still installing hx, or has no path for the project is disabled and says why),
  GPUs per run and ``wait for GPUs`` (SSH hosts) or partition, time and account (SLURM
  hosts; a blank field keeps the host's default from ``environments.yaml``), seeds
  (``4, 5, 6`` or ``1-3``), the command with ``{seed}``, and a required hypothesis. The
  preview shows the first seed's command as it will run. ``Copy as CLI`` copies the same
  ``hx launch`` lines. ``Launch N`` starts one run per seed; a double click still starts
  each seed once, and after a refused seed ``Launch`` sends only the seeds that did not
  start (and needs free GPUs only for those); the preview and ``Copy as CLI`` then show
  only those seeds too, so pasted lines never start a seed twice. A seed that got no answer
  may have started: the form locks, and ``Resend seed N`` sends that seed alone under the
  same id (also when its GPU now looks taken, maybe by that seed), until the hub answers
  with its run; then the form unlocks for the seeds after it. A launch on a host names the
  project; the hub pins the code (its checkout's commit and uncommitted diff), and
  ``Rerun sweep`` pins the template run's commit when that run had no uncommitted changes.
  ``New run`` proposes seeds after every seed of the template's config, archived runs
  included.
- **Sweep** (``/s/<project>/<sweep_id>``): the best cell and its score as the headline,
  progress, cost and ETA, a params × metric heat table (a sortable table for one param,
  more than two, or sampled ranges), seed dots with 95% intervals (dots only from the
  cell's own runs), and the sweep's runs on their hosts. Actions: ``Copy as CLI`` (the
  same ``hx sweep``), ``Cancel queued``, ``Add seeds`` (new seeds for every cell; after a
  failed try it proposes the same seeds again, not the ones after them, and the hub starts
  only their missing runs), and ``Rerun sweep`` (the best cell again, in the Launch
  dialog).
- **Run** (``/r/<run_id>``): the hypothesis as title, status, stat strip, the task kind's
  run panels, where everything is (code, data, run folder, logs, predictions,
  checkpoints), scores by metric version, notes, and actions. ``?log=stderr`` opens a log
  tail; ``?example=<id>`` picks a traced example on agent tasks. A run on a host also
  shows where it runs (host, ``CUDA_VISIBLE_DEVICES``, SLURM job and node), its place in
  the host queue while it waits, ``stale`` with the time since the hub last heard from the
  host (never ``lost``: only the host decides that), why it was lost (the reason
  from its ``run.lost`` event when the page saw that event, else what the record says: job,
  node, end time, exit code), and its cost (``—`` when the host has no
  ``usd_per_gpu_hour``, so its GPU hours have no price). Times since a moment (waiting,
  wall, unreachable) move on every 10 s while the run is not over, also when the host
  sends nothing new. The Queue panel lists the host's whole queue.
- **Examples** (``/x/<a>/<b>?metric=<name>``): what run B fixes and breaks against run A,
  with the paired sign test.
- **View editor** (``/t/<project>/<task>/edit/<view>``, ``new`` for a new view): YAML on
  the left with inline validation, a live preview on the right, then Save (writes
  ``.hypothex/views/<task>/<name>.yaml``) or Copy as CLI. A new view cannot take the
  name of a view that is already there: open that view to edit it.

Press ``⌘K`` (``Ctrl K`` on Linux and Windows) to find a run, task or path. The
colour-mode button in the header switches light and dark mode.

Build before packaging
----------------------

The built UI lives in ``src/hypothex/ui_dist/``, which git ignores. Build it before you
build the wheel, so the wheel ships it:

.. code-block:: bash

   cd ui && bun install && bun run build && cd ..
   uv build

Without ``ui_dist``, ``hx serve`` serves the API only, and the wheel has no UI.

Develop
-------

.. code-block:: bash

   uv run hx serve                 # API on 127.0.0.1:7777
   cd ui && bun run dev            # http://localhost:5173

The Vite dev server reloads on save and proxies ``/api`` (HTTP and WebSocket) to
``hx serve``. Set ``HX_API=http://host:port`` to proxy to another server.

Test
----

.. code-block:: bash

   cd ui
   bun test                        # unit and component tests
   bun run build                   # the smoke tests use the built UI
   bunx playwright install chromium    # once
   bunx playwright test            # smoke tests, light and dark

Each ``bunx playwright test`` gets its own directory, ``ui/e2e/.runs/run-XXXXXX``
(``HX_E2E_RUN_DIR``), so two suites in one checkout never wipe each other's homes. It
seeds a fresh demo home in ``home`` there with ``hx demo`` and serves it with ``hx serve``
on a free port the OS picks for that run (never a fixed port, so it can never meet an
``hx serve`` you left running), so it never touches your own ``~/.hypothex``. The runner
hands the port to its workers and demo servers in ``HX_E2E_PORT`` (``HX_E2E_HOSTS_PORT``
for the hosts demo).

The ``hosts-*`` projects run against a second demo hub, seeded in ``home-hosts`` in the
same directory with ``hx demo --with-hosts`` (fake hosts that run on this machine), on its
own free port.
Both demo servers run with ``HYPOTHEX_SSH=false`` and ``HYPOTHEX_SCP=false``, so no test
can reach a real host. Playwright never reuses a server that already answers, stops at once
when a demo server cannot start, and every test first checks that the hub answers with the
identity written into its fresh home (``environment.json``), so no host route, note or
launch can reach another server. When a demo server stops, it waits for its hub's own
shutdown, then kills every process left under its own home (a hub that crashed or hung
leaves its fake hosts and runs behind), never the other demo server's.
``bun e2e/shutdown-check.ts`` stops the hosts demo three ways (SIGTERM, as Playwright
does; the hub killed; the hub stuck past the shutdown wait) and fails if a demo run or
fake host is left running.
