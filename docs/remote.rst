Remote hosts and sweeps
=======================

Hypothex runs experiments on SSH GPU boxes and SLURM clusters. Your machine is the
**hub**: it runs ``hx serve``, keeps the index of every project, and serves the UI.
Each host runs its own **env server** (``hx serve`` on the host). The env server
starts, watches, and records its runs, so a run keeps going when your laptop sleeps
or the network drops. The hub copies the results back as they happen.

Env servers listen on ``127.0.0.1`` only, and the hub reaches them through an SSH
tunnel made with your own ``ssh`` and ``~/.ssh/config``. On a shared GPU box or a
SLURM login node other users can reach ``127.0.0.1`` too, so an env server answers
only requests that carry its token (``Authorization: Bearer``). The token is new for
each start and is kept in ``~/.hypothex/serve/server.json`` on the host (readable only
by you); the hub reads it over ``ssh``. Only the descriptor
``/.well-known/hypothex/environment`` is open. The hub's own ``hx serve`` (the UI on
your machine) works as before, without a token.

Add a host
----------

.. code-block:: bash

   hx hosts add gpu1 --ssh gpu1-alias --usd-per-gpu-hour 2.10
   hx hosts add cluster --ssh login-node --slurm --partition gpu --time 08:00:00
   hx hosts map deepretro gpu1 /home/sv/code/DeepRetro

``--ssh`` takes a ``Host`` from ``~/.ssh/config``. ``hx hosts map`` tells the hub where
a project's checkout is on the host; runs there use it. Hosts are kept in
``~/.hypothex/environments.yaml`` on the hub:

.. code-block:: yaml

   environments:
     gpu1:
       route: ssh
       ssh_alias: gpu1-alias
       kind: ssh
       home: ~/.hypothex
       usd_per_gpu_hour: 2.10
       projects: {deepretro: /home/sv/code/DeepRetro}
     cluster:
       route: ssh
       ssh_alias: login-node
       kind: slurm
       slurm: {partition: gpu, account: null, time: "08:00:00", gpus: 1}

``hx hosts add --ssh`` sets the host up: it checks the host (OS, Python or ``uv``,
``nvidia-smi``, ``sbatch``), installs this version of Hypothex into
``~/.hypothex/runtime`` on the host, and starts the env server (or reuses a healthy
one). The wheel comes from your source checkout (``uv build``); a hub installed with
``uv tool install hypothex`` downloads its own release from PyPI instead (no network,
or an unpublished version: run ``hx`` from a source checkout). A SLURM host's home must
support ``flock`` (on Lustre, mount with ``-o flock``); the env server refuses to start
otherwise, and ``hx hosts add --slurm`` adds nothing. While ``hx serve`` runs on the hub
it connects every host: it starts the env server again when it is gone (after a reboot)
and opens the tunnel. A dropped connection is retried after 3, 4, 8, and then every 16
seconds; a host that refuses the hub's token (HTTP 401/403) shows ``error`` and is not
retried until ``hx hosts connect``. ``hx hosts add``, ``map``, and ``rm`` update a
running hub at once.

.. code-block:: bash

   hx hosts list              # what environments.yaml says (no hub needed)
   hx hosts status --json     # live: state, GPUs busy, queue, SLURM jobs, cost today
   hx hosts disconnect gpu1   # stop watching gpu1; its runs keep going
   hx hosts connect gpu1      # watch it again
   hx hosts upgrade gpu1      # install this Hypothex version on gpu1 and restart its server
   hx hosts rm gpu1

Host states: ``connecting``, ``bootstrapping``, ``connected``, ``stale`` (no answer
for 60 s; its runs show as stale, they are not lost), ``upgrade`` (the host runs an
incompatible Hypothex; use ``hx hosts upgrade``), ``error``, and ``disabled``
(disconnected). ``GET /api/v1/hosts`` lists the hub itself first as ``local``.
``hx hosts disconnect`` is kept across hub restarts; connecting, disconnecting, or
adding one host never drops the others. A broken ``environments.yaml`` does not stop
``hx serve``: the hosts show ``error`` with the message until the file is fixed. The UI
shows a banner for a host ``stale`` longer than ``stale_banner_hours`` (top of
``environments.yaml``, default 24).

The CLI and the MCP server reach the hub at ``HYPOTHEX_HUB_URL`` (default
``http://127.0.0.1:7777``).

Launch on a host
----------------

.. code-block:: bash

   hx launch --host gpu1 --gpus 2 --queue -t TASK -H "why" -- python train.py --seed '{seed}'
   hx launch --host cluster --gpus 2 --time 04:00:00 -t TASK -H "why" -- python train.py

- The run uses the exact commit you launched from: the hub sends your checkout's
  ``HEAD`` and your uncommitted changes (``git diff HEAD``). The host runs ``git
  fetch`` when it does not have that commit (push it first to a remote the host can
  fetch), and applies the changes in a clean git worktree; its own checkout is not
  touched. A diff that is not UTF-8 text, or is larger than 5 MiB, is refused: commit
  it first. New files that git does not track yet are not in ``git diff HEAD``;
  ``hx launch`` names them in a warning (``git add`` them to send them).
- ``hx launch --host`` and ``hx sweep --host`` work from any machine that reaches the
  hub: they send the project name, commit, and diff, never a local path.
- SSH hosts keep a queue. A GPU is free when no run holds it and ``nvidia-smi`` shows
  no other process on it. Queued runs start in order (first fit) with
  ``CUDA_VISIBLE_DEVICES`` set.
- SLURM hosts submit with ``sbatch`` (``--gpus``, ``--time``, ``--partition``,
  ``--account``; defaults from the host entry) and check ``squeue``/``sacct`` every
  30 s. ``hx stop`` runs ``scancel``. A job that disappears without an exit record is
  marked ``lost``. A rerun keeps the run's GPUs and SLURM settings. SLURM runs are
  always submitted: ``hx rerun --foreground`` is refused there. A run targets one host;
  there is no queue across hosts.
- On a SLURM cluster only the env server on the login node opens the SQLite files
  (``index.db``, ``events.db``): SQLite does not work across machines on NFS, Lustre,
  or GPFS. The job on the compute node writes only files in the run's folder
  (``run.yaml``, logs, metrics, and ``exit.json``); the env server reads them every
  30 s and records the run's start and end.
- Stop, rerun, re-infer, re-evaluate, tags, stars, and notes on a remote run go to its
  host with the same command id, so a repeated click still acts once. ``hx`` and the MCP
  tools send them through the hub too (they never act on the hub's copy). When the run's
  host is no longer in ``environments.yaml``, stop, rerun, re-infer, and re-evaluate
  answer ``503`` instead of acting on the hub's copy.
- Cost: ``gpu_hours = wall time x GPUs`` and ``usd = gpu_hours x usd_per_gpu_hour``,
  plus API cost from ``usage.jsonl``.

Sweeps
------

.. code-block:: bash

   hx sweep -t TASK -H "lr x beam" --grid lr=1e-4,3e-4,1e-3 --grid beam=5,10 \
       --seeds 3 --host gpu1 --gpus 2 --queue -- \
       python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'

Every combination runs once per seed (here 3 x 2 x 3 = 18 runs), tagged
``sweep:<hub>:<id>`` (``<hub>``: the first 8 characters of the hub's environment id,
so two hubs using one host never mix their sweeps). Seed 1 of every combination
starts first, so a queue fills the whole
table early. The command must use every swept name; each run also gets its seed as
``$HYPOTHEX_SEED``. ``--seeds 3`` means seeds 1, 2, 3; ``--seeds 1,2,5`` lists them.
For random search give ranges and a count: ``--random 20 --param lr=1e-5:1e-3:log``.
A sweep has at most 1000 runs.

.. code-block:: bash

   hx sweeps --json                     # newest first, with the best cell
   hx sweep show s-7f3a --json          # progress, params x primary metric, best, cost
   hx sweep extend s-7f3a --seeds 4,5
   hx sweep cancel s-7f3a               # stop queued runs; running runs keep going

The sweep is saved at ``<store>/<project>/sweeps/<id>.yaml``; the UI shows it at
``/s/<project>/<id>``. If a host drops in the middle of a launch, the sweep keeps the
runs that started; ``hx sweep extend`` with the same seeds then starts only the missing
runs.

Big files
---------

The hub copies each run's small files (``run.yaml``, scores, metrics, notes,
predictions, traces; up to 200 MB each) and the last 8 MiB of each log. A file that
only grows (logs, ``*.jsonl``) is copied from where the last copy ended, so a long
run's logs do not cross the tunnel again every 10 s. Checkpoints and other artifacts
stay on the host; the hub shows them with the host's name. Copy one when you need it:

.. code-block:: bash

   hx pull RUN_ID                                       # the latest checkpoint
   hx pull RUN_ID --artifact predictions/predictions.jsonl

The copy goes to ``pulled/`` in the run's folder on the hub. A path outside the run
folder must be one of the run's own artifacts, and ``scp`` runs in SFTP mode
(``scp -s``), so a path is never read by the host's shell.

A project that is registered only on a host still shows on the hub: the hub copies
its ``hypothex.yaml`` snapshot from the host with its first run, so tasks,
leaderboards, and sweep tables work. To launch it from the hub, use ``--host`` (the
host's checkout runs it) or run it once from a checkout on the hub (``hx run``
registers the project).

Keep an env server running
--------------------------

On a host where the env server should survive reboots and logouts:

.. code-block:: bash

   hx service install --kind slurm      # or --kind ssh

This writes a systemd user unit (Linux) or a launchd agent (macOS) and prints the
commands that enable it; Hypothex never runs them for you. ``hx service uninstall``
removes the file and prints how to stop the server. The hub never stops an env server
that it did not start.

To run an env server by hand: ``hx serve --kind ssh --port 0``. The port it picks and
its token are written to ``~/.hypothex/serve/server.json``. ``--no-auth`` drops the
token; use it only for test hosts that the hub reaches by ``route: url``.

Try it without hosts
--------------------

.. code-block:: bash

   hx --home /tmp/hx-demo demo --with-hosts
   hx --home /tmp/hx-demo serve

The demo adds two fake hosts as separate homes under ``/tmp/hx-demo/demo-hosts``:
``gpu1`` (8 fake A100 GPUs, two of them used by other people) and ``cluster`` (SLURM,
with fake ``sbatch``, ``squeue``, and ``sacct``). ``hx serve`` starts both, fills the
GPU queue on ``gpu1`` with three running and three queued runs of sweep ``s-7f3a``, and
stops them when it exits. No real host is contacted.

MCP tools
---------

``list_hosts``, ``launch_run`` (with ``host``, ``gpus``, ``queue``), ``launch_sweep``,
``get_sweep``, ``cancel_sweep``, ``extend_sweep``, and ``pull_artifact``. The tools
that need live hosts call the hub at ``HYPOTHEX_HUB_URL``.
