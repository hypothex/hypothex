Troubleshooting
===============

Each entry gives the symptom, the cause, and what to do. Add ``--json`` to a command to
get the error as ``{"error": ..., "type": ...}``.

The hub
-------

**"the hub at http://127.0.0.1:7777 did not answer ...; start it with `hx serve`"**
   Host commands (``hx hosts status``, ``hx launch --host``, ``hx sweep --host``,
   ``hx pull``) and the MCP host tools need ``hx serve`` on the hub. Start it, or set
   ``HYPOTHEX_HUB_URL`` to the hub's address.

**"refusing to serve on '0.0.0.0' without authentication ..."**
   ``hx serve --host`` with a non-loopback address needs ``HYPOTHEX_SERVE_TOKEN``. Or
   keep ``127.0.0.1`` and use an SSH tunnel. See :doc:`security`.

**"an hx server already serves this home on port N (pid P); use it, or stop it first"**
   One home has one server. Use the running server, stop it, or start the new one with
   another ``--home``.

**"missing or wrong bearer token" (401)**
   The server has a token. Set ``HYPOTHEX_HUB_TOKEN`` for the CLI and MCP, or send
   ``Authorization: Bearer <token>``.

Adding a host
-------------

**ssh fails, or asks for a password**
   Hypothex runs ``ssh -o BatchMode=yes``, so a password prompt is an error. Check that
   ``ssh -o BatchMode=yes ALIAS true`` works from the hub (key login, or a running
   ``ssh-agent``), and that ``ALIAS`` is a ``Host`` in ``~/.ssh/config``.

**"... has no sbatch on PATH; drop --slurm or use the login node"**
   ``--slurm`` needs ``sbatch`` on the host. Point ``--ssh`` at a login node.

**"uv is missing on the host and ... failed (no network?)"**
   The host has no ``uv`` and could not download it. Install ``uv`` on the host by
   hand, then run ``hx hosts add`` again. The install also needs access to the package
   index for Hypothex's dependencies.

**The wheel cannot be downloaded**
   A hub installed with ``uv tool install`` downloads its own release from PyPI. With
   no network, or with an unpublished version, run ``hx`` from a source checkout: it
   builds the wheel with ``uv build``.

**"host gpu-box exists; remove it first with `hx hosts rm gpu-box`"**
   Host names are unique. Remove the old entry, or pick another name.

**The env server does not start on a SLURM login node**
   The home must support ``flock``. On Lustre, mount with ``-o flock``, or use
   ``--remote-home`` on a filesystem that supports it.

Where to look on the host (default home ``~/.hypothex``):

- ``~/.hypothex/serve/server.log``: the env server's log.
- ``~/.hypothex/runtime/install.log`` and ``uv-install.log``: the install.
- ``~/.hypothex/serve/server.json``: the running server's pid and port (and token:
  keep it private).

Host states
-----------

**A host shows ``stale``**
   The hub got no answer for 60 seconds. Its runs keep going on the host and are not
   lost; do not rerun them. The hub tries again on its own (after 3, 4, 8, then every
   16 seconds). Check the network or VPN, then ``hx hosts connect HOST``.

**A host shows ``error`` with an auth message**
   The host refused the hub's token (401 or 403), for example after the env server was
   restarted by hand with another token. The hub does not retry. Run
   ``hx hosts connect HOST``; it reads the current token over ``ssh``.

**A host shows ``upgrade``**
   The host runs an incompatible Hypothex. Run ``hx hosts upgrade HOST``.

**"HOST still runs hx X (pid P); stop that server ..."**
   ``hx hosts upgrade`` stops only a server that Hypothex started. Stop the other one
   (``hx service uninstall`` on the host, or kill the pid), then upgrade again.

**Every host shows ``error`` with a path to environments.yaml**
   The file does not parse or does not match the schema. The message names the line or
   field. Fix the file; the hub reads it again on ``hx hosts add``, ``map``, ``rm``,
   ``connect``, or a restart.

Launching
---------

**"project P has no checkout on HOST; run `hx hosts map P HOST <path on HOST>`"**
   Tell the hub where the project is on the host: ``hx hosts map``.

**"commit abc123 is not in /path, even after `git fetch`; push it to a remote this host can fetch"**
   The host does not have the commit you launched from. ``git push``, then launch
   again.

**"warning: N untracked file(s) are not sent to the host"**
   New files are not in ``git diff HEAD``. ``git add`` them (no commit needed), then
   launch again.

**The diff is refused**
   A diff larger than 5 MiB, or one that is not UTF-8 text (binary files), is not sent.
   Commit the change and push it.

**"--config is not sent to hosts ..."**
   Commit the config file and pass its path with ``--var``.

**"2 GPUs requested; 1 of 8 free; add --queue to wait for them"**
   Not enough GPUs are free now. Add ``--queue``, or ask for fewer.

**A queued run never starts**
   The queue moves only while an env server runs on that machine (every 5 seconds).
   Check ``hx hosts status``: the host must be ``connected``. A large run waits until
   enough GPUs are free at the same time, and smaller runs behind it can start first.
   ``hx hosts status HOST --json`` shows which runs or outside processes hold the
   GPUs.

**"host H is not a SLURM host; drop --partition/--time/--account"**
   These options are for SLURM hosts only.

**"SLURM runs are always submitted; drop --foreground"**
   SLURM runs cannot run in the foreground.

SLURM
-----

**A run stays ``queued`` with "submission outcome unknown; check squeue/sacct"**
   ``sbatch`` did not answer clearly, and the cluster's accounting does not store job
   comments, so Hypothex cannot prove whether the job exists. Look with
   ``squeue --me`` and ``sacct``. When there is no job, ``hx stop RUN_ID``.

**A run is ``lost`` with "SLURM ended job N with NODE_FAIL ..."**
   The job ended without an exit record (a node failure, a time limit hit before the
   run could write it, a preemption). Read ``logs/slurm-N.out`` in the run folder.
   Rerun it with ``hx rerun RUN_ID``.

**An extra sbatch option is refused**
   Each ``slurm.extra`` item must be one option token and must not set an option
   Hypothex owns. See :doc:`slurm`.

Remote runs
-----------

**Stop, rerun, re-infer, or re-evaluate answers 503**
   The run's host is no longer in ``environments.yaml``, or it is not connected. Add
   the host again, or wait until it is ``connected``.

**A checkpoint is not on the hub**
   Big files stay on the host. Copy one with ``hx pull RUN_ID --artifact checkpoint``.

**A file of a remote run is missing on the hub**
   The hub copies files up to 200 MB (and the last 8 MiB of each log). Larger files
   stay on the host; copy one with ``hx pull RUN_ID --artifact PATH``.

Sweeps
------

**"the command never uses {x}; every swept param must appear in it"**
   Put ``'{x}'`` in the command for each ``--grid`` or ``--param`` name.

**"command uses {y} but no sweep param or built-in fills it"**
   Remove ``{y}`` from the command or add ``--grid y=...``.

**"sweep would launch N runs; the limit is 1000"**
   Use fewer values, fewer seeds, or ``--random``.

**"sweep s-1234 exists in a, b; pass --project"**
   Add ``-p PROJECT``.
