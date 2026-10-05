Remote hosts
============

Hypothex runs experiments on SSH GPU boxes and SLURM clusters. This page explains the
parts, how to add a host, and how runs reach it. The GPU queue, SLURM, sweeps, and cost
have their own pages: :doc:`gpus`, :doc:`slurm`, :doc:`sweeps`, :doc:`cost`.

How it fits together
--------------------

- The **hub** is your machine. It runs ``hx serve``, keeps the index of every project,
  serves the UI, and connects to every host in ``~/.hypothex/environments.yaml``.
- Each host runs its own **env server** (``hx serve --kind ssh`` or ``--kind slurm``).
  The env server starts, watches, and records its runs. A run keeps going when your
  laptop sleeps or the network drops.
- The hub reaches an env server through an **SSH tunnel** (``ssh -N -L``) made with
  your own ``ssh`` and ``~/.ssh/config``. The env server listens on ``127.0.0.1`` only.
- The hub subscribes to each host's event stream and **mirrors** the runs: it copies
  the small files of each run to the hub as they change. Big files stay on the host.
  The hub keeps its place in each host's stream (a *cursor*), so after a reconnect it
  reads only what it missed. When a host's event log starts again (its ``events.db``
  was deleted or restored from a backup, but the host kept its id), the hub sees that
  the host is behind the cursor and reads the whole log again; nothing is copied
  twice.

The env server asks for a bearer token on every request. See :doc:`security`.

Before you start
----------------

- ``ssh ALIAS`` works from the hub without a password prompt (key login or an agent).
  Hypothex runs ``ssh`` with ``-o BatchMode=yes``, so it never asks for a password.
- The host has a git checkout of your project, and can ``git fetch`` the commits you
  launch (push them first).
- The host has ``uv`` on ``PATH`` or in ``~/.local/bin`` or ``~/.cargo/bin``. Hypothex
  does not install ``uv`` unless you ask for it with ``--install-uv``; then the host
  needs ``curl`` or ``wget`` and network access to ``astral.sh``. The install also
  needs access to the package index for Hypothex's dependencies.
- A SLURM host: run the env server on a login node, and give it a home on a shared
  filesystem that supports ``flock`` (see :doc:`slurm`).

Add a host
----------

.. code-block:: bash

   hx hosts add gpu-box --ssh gpu-box --usd-per-gpu-hour 2.10
   hx hosts add cluster --ssh cluster-login --slurm --partition gpu --time 08:00:00
   hx hosts map toy-classifier gpu-box /home/me/code/toy-classifier

``hx hosts add NAME`` options:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Meaning
   * - ``--ssh ALIAS``
     - A ``Host`` from ``~/.ssh/config`` (or ``user@host``). Give ``--ssh`` or
       ``--url``, not both.
   * - ``--url URL``
     - An env server that already listens at ``URL`` (tests and special setups). No
       bootstrap.
   * - ``--slurm``
     - The host is a SLURM login node.
   * - ``--partition P``, ``--account A``
     - Default SLURM partition and account (need ``--slurm``).
   * - ``--time T``
     - Default SLURM time limit (default ``02:00:00``).
   * - ``--gpus N``
     - Default SLURM GPUs per job (default 1).
   * - ``--remote-home PATH``
     - The Hypothex home on the host (default ``~/.hypothex``).
   * - ``--usd-per-gpu-hour X``
     - The price of one GPU hour, for :doc:`cost`.
   * - ``--install-uv``
     - When the host has no ``uv``, run the official ``uv`` installer
       (``https://astral.sh/uv/install.sh``) there. Without it, a host without ``uv``
       is not added, and the error tells you to install ``uv``.
   * - ``--json``
     - Print machine-readable JSON.

A host name uses ``a-z``, ``0-9``, ``-`` and ``_`` (up to 32 characters). ``local``
is reserved for the hub.

What ``hx hosts add --ssh`` does
--------------------------------

``hx hosts add --ssh`` sets the host up over ``ssh`` in three steps (the
*bootstrap*):

1. **Probe**: it checks the OS, Python, ``uv``, ``nvidia-smi``, and ``sbatch``. With
   ``--slurm`` and no ``sbatch`` on the host, nothing is added.
2. **Install**: it builds a wheel of the Hypothex version you run (``uv build``) from
   a source checkout, or downloads that release from PyPI for a hub installed with
   ``uv tool install``. It copies the wheel with ``scp`` and installs it with
   ``uv tool install --force`` into ``~/.hypothex/runtime`` on the host. If the host
   has no ``uv``, the install stops before the wheel is copied, with
   ``uv is missing on the host``. Only with ``--install-uv`` does the official
   installer put ``uv`` into ``~/.local/bin`` (its log is
   ``~/.hypothex/runtime/uv-install.log``).
3. **Start**: it starts ``hx serve --host 127.0.0.1 --port 0`` on the host, or reuses
   a healthy env server for that home. The port and the token go into
   ``~/.hypothex/serve/server.json`` on the host (mode 0600).

Then it writes the host to ``environments.yaml`` and, when the hub runs, the hub
connects at once. Without a running hub, the next ``hx serve`` connects it.

The environments file
---------------------

Hosts are kept in ``~/.hypothex/environments.yaml`` on the hub. ``hx hosts add``,
``map``, and ``rm`` write it; you can also edit it by hand.

.. code-block:: yaml

   stale_banner_hours: 24          # UI banner when a host is stale this long
   environments:
     gpu-box:
       route: ssh                  # ssh | url
       ssh_alias: gpu-box
       kind: ssh                   # ssh | slurm
       home: ~/.hypothex
       usd_per_gpu_hour: 2.10
       projects: {toy-classifier: /home/me/code/toy-classifier}
     cluster:
       route: ssh
       ssh_alias: cluster-login
       kind: slurm
       slurm: {partition: gpu, account: null, time: "08:00:00", gpus: 1, extra: ["--qos=normal"]}

``slurm.extra`` holds more ``sbatch`` options, one option per item. See :doc:`slurm`.
A broken file does not stop ``hx serve``: every host shows ``error`` with the message
until you fix the file.

Map a project
-------------

.. code-block:: bash

   hx hosts map PROJECT HOST PATH

``hx hosts map`` tells the hub where a project's checkout is on a host. Runs on that
host use it. ``PATH`` is absolute or starts with ``~``. A running hub uses the new map
at once.

Manage hosts
------------

.. code-block:: bash

   hx hosts list                 # what environments.yaml says (no hub needed)
   hx hosts status               # live: state, GPUs busy, queue, SLURM jobs, cost today
   hx hosts status gpu-box --json
   hx hosts disconnect gpu-box   # stop watching gpu-box; its runs keep going
   hx hosts connect gpu-box      # watch it again (also clears an error)
   hx hosts upgrade gpu-box      # install this Hypothex version and restart its server
                                 # (--install-uv: also install uv when the host has none)
   hx hosts rm gpu-box           # forget it; its env server and runs keep going

``hx hosts status`` columns: host, kind, state, since, GPUs busy (busy/total), queue,
SLURM pending/running, cost today, message. The first row is always the hub itself,
named ``local``.

``hx hosts disconnect`` is kept across hub restarts. Connecting, disconnecting, or
adding one host never drops the other hosts.

Tunnel recovery
---------------

The hub records each tunnel under ``<home>/hub/tunnels/`` with the tunnel and
owner PIDs, both process birth times, and the exact forwarding arguments. After
an owner dies, a later hub can stop the recorded tunnel only when its birth time
and arguments still match. Reusing a PID does not transfer ownership. Cleanup
waits at most five seconds after SIGTERM, then checks identity again before
SIGKILL and another five-second wait.

A process lookup failure or an incomplete stop keeps the record for a later
attempt. Older records without birth times never authorize a signal: if the
process is still present, verify and stop the old tunnel manually; the record
can be removed once that process is gone. A registry-write failure while starting
a new tunnel stops the spawned process before returning the error.

Host states
-----------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - State
     - Meaning
   * - ``connecting``
     - The hub opens the tunnel and reads the descriptor.
   * - ``bootstrapping``
     - The hub checks the env server over ``ssh`` and starts it again when it is gone
       (for example after a reboot).
   * - ``connected``
     - Events and files flow.
   * - ``stale``
     - No answer for 60 s. Its runs show as stale; they are not lost.
   * - ``upgrade``
     - The host runs an incompatible Hypothex. Run ``hx hosts upgrade HOST``.
   * - ``error``
     - The connection failed; the message says why.
   * - ``disabled``
     - You ran ``hx hosts disconnect``.

A dropped connection is tried again after 3, 4, 8, and then every 16 seconds. A host
that refuses the hub's token (HTTP 401 or 403) shows ``error`` and is not tried again
until ``hx hosts connect``. The UI shows a banner for a host that is ``stale`` longer
than ``stale_banner_hours``.

Where the CLI finds the hub
---------------------------

Commands that need live hosts (``hx hosts status``, ``hx launch --host``,
``hx sweep --host``, ``hx pull``, and the MCP host tools) call the hub at
``HYPOTHEX_HUB_URL`` (default ``http://127.0.0.1:7777``). They send
``HYPOTHEX_HUB_TOKEN`` when it is set. For a hub on this machine they read the token
from the hub's own ``~/.hypothex/serve/server.json`` when it has one.

.. code-block:: bash

   HYPOTHEX_HUB_URL=http://127.0.0.1:7777 hx hosts status

Launch on a host
----------------

.. code-block:: bash

   hx launch --host gpu-box --gpus 2 --queue -t TASK -H "why" -- python train.py --seed '{seed}'
   hx launch --host cluster --gpus 2 --time 04:00:00 -t TASK -H "why" -- python train.py
   hx launch --host gpu-box --wait -t TASK -H "why" -- python eval.py   # block until it ends

``hx launch`` takes the same options as ``hx run``, plus ``--host``, ``--gpus``,
``--queue``, ``--partition``, ``--time``, ``--account``, and ``--wait``.

- The run uses the exact commit you launched from. The CLI sends your checkout's
  ``HEAD`` and your uncommitted changes (``git diff HEAD``). The host runs
  ``git fetch`` when it does not have that commit, and applies the changes in a clean
  git worktree; its own checkout is not touched.
- Queued pinned runs share a staging checkout until execution starts. Each execution
  checkout is reserved exclusively; an existing, unverified destination makes the
  run fail without running in or deleting that directory. SLURM creates the checkout
  before submission and records its completion so the compute node can reuse it.
- A diff that is not UTF-8 text, or is larger than 5 MiB, is refused: commit it first.
- New files that git does not track are not in ``git diff HEAD``. ``hx launch`` names
  them in a warning; ``git add`` them to send them.
- ``--config`` is not sent to hosts. Commit the file and pass its path with ``--var``.
- ``hx launch --host`` works from any machine that reaches the hub: it sends the
  project name, commit, and diff, never a local path.
- A run targets one host. There is no queue across hosts.

Act on remote runs
------------------

``hx stop``, ``rerun``, ``reinfer``, ``reeval``, ``tag``, ``star``, ``archive``, and
``note`` on a remote run go through the hub to the run's host, with one command id, so
a repeated call still acts once. They never change only the hub's copy. When the
run's host is no longer in ``environments.yaml``, stop, rerun, re-infer, and
re-evaluate answer ``503``. So do tag, star, archive, and note when the hub mirrored the
run from that host: the host's copy would replace the hub's when the host is added
back. ``--foreground`` is refused for a remote run.

A task re-evaluation through the hub (``POST /api/v1/tasks/{project}/{task}/reeval``)
scores the hub's own runs on the hub in one pass and sends each remote run to its
host. The hub waits up to 600 s for each host's answer (``REEVAL_FORWARD_SECONDS``),
as scoring can take long. A run whose host is down or gone is listed in ``skipped``,
and so are the host's later runs in that call. The hub never scores a mirrored run
itself: the host does, and the mirror then copies the host's ``scores.jsonl``.

What the hub copies
-------------------

The hub copies each run's small files: ``run.yaml``, ``scores.jsonl``,
``metrics.jsonl``, ``notes.md``, ``usage.jsonl``, ``config.yaml``, ``git.diff``,
``git.stat``, and the folders ``predictions``, ``traces``, ``samples``, ``env``, and
``logs``. Each file can be up to 200 MiB; of each log, the hub keeps the last 8 MiB.
Checkpoints and other artifacts stay on the host; the hub shows them with the host's
name. Copy one when you need it:

.. code-block:: bash

   hx pull RUN_ID                                          # the latest checkpoint
   hx pull RUN_ID --artifact predictions/predictions.jsonl
   hx pull RUN_ID --artifact checkpoint --json             # prints {"local_path": ...}

``--artifact`` is an artifact kind (the latest of that kind), an artifact path, or a
path in the run folder. The copy goes to ``pulled/`` in the run's folder on the hub.
A path outside the run folder must be one of the run's own artifacts. ``scp`` runs in
SFTP mode (``scp -s``), so the host's shell never reads the path.

A project that is registered only on a host still shows on the hub: the hub copies its
``hypothex.yaml`` snapshot from the host with its first run. Tasks, leaderboards, and
sweep tables then work on the hub.

Keep an env server running
--------------------------

The hub starts an env server again when it is gone (after a reboot). To keep one
running without the hub, install a user service on the host:

.. code-block:: bash

   hx service install --kind ssh        # or --kind slurm
   hx service uninstall

``hx service install`` writes a systemd user unit (Linux) or a launchd agent (macOS)
and prints the commands that enable it; Hypothex never runs them for you.
``hx service uninstall`` removes the file and prints how to stop the server. The hub
never stops an env server that it did not start.

Run an env server by hand
-------------------------

.. code-block:: bash

   hx serve --kind ssh --port 0         # on the host

The port it picks and its token go into ``~/.hypothex/serve/server.json``. The kind is
saved, so a later ``hx serve`` on that home uses it again. ``--no-auth`` drops the
token; use it only for test hosts that the hub reaches with ``hx hosts add --url``.

Sweeps on a host
----------------

.. code-block:: bash

   hx sweep -t TASK -H "lr x beam" --grid lr=1e-4,3e-4 --grid beam=5,10 --seeds 3 \
       --host gpu-box --gpus 1 --queue -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'
   hx sweep extend SWEEP_ID --seeds 4,5

A sweep sends one commit and diff for all its runs. See :doc:`sweeps`.

MCP tools
---------

``list_hosts``, ``launch_run`` (with ``host``, ``gpus``, ``queue``), ``launch_sweep``,
``get_sweep``, ``cancel_sweep``, ``extend_sweep``, and ``pull_artifact``. They call the
hub at ``HYPOTHEX_HUB_URL``. See :doc:`mcp`.

.. _demo-hosts:

Try it without hosts
--------------------

.. code-block:: bash

   hx --home /tmp/hx-demo demo --with-hosts
   hx --home /tmp/hx-demo serve

The demo adds two fake hosts as separate homes under ``/tmp/hx-demo/demo-hosts``:
``gpu1`` (8 fake A100 GPUs, two of them used by other people) and ``cluster`` (SLURM,
with fake ``sbatch``, ``squeue``, and ``sacct``). ``hx serve`` starts both, fills the
GPU queue on ``gpu1`` with three running and three queued runs of sweep ``s-7f3a``,
and stops them when it exits. No real host is contacted.
