SLURM clusters
==============

On a SLURM cluster the env server runs on a **login node** (``hx serve --kind
slurm``). It submits each run as one batch job with ``sbatch``, tracks the job with
``squeue`` and ``sacct``, and cancels it with ``scancel``.

Add a cluster
-------------

.. code-block:: bash

   hx hosts add cluster --ssh cluster-login --slurm --partition gpu --account my-lab \
       --time 08:00:00 --gpus 1 --usd-per-gpu-hour 1.20
   hx hosts map toy-classifier cluster /home/me/code/toy-classifier

``--ssh`` names the login node. The probe needs ``sbatch`` on the login node's
``PATH``; without it, nothing is added.

The Hypothex home on the cluster (``--remote-home``, default ``~/.hypothex``) must be
on a filesystem that the login node and the compute nodes share, and it must support
``flock``. On Lustre, mount with ``-o flock``. The env server refuses to start without
``flock``, and ``hx hosts add --slurm`` then adds nothing.

Launch
------

.. code-block:: bash

   hx launch --host cluster -t TASK -H "why" -- python train.py --seed '{seed}'
   hx launch --host cluster --gpus 4 --time 1-00:00:00 --partition long --account my-lab \
       -t TASK -H "why" -- python train.py

The SLURM settings of a run come from the host's ``slurm`` block in
``environments.yaml``. ``--partition``, ``--time``, and ``--account`` on ``hx launch``
override them for that run, and ``--gpus N`` overrides ``slurm.gpus``. These options
need a SLURM host; on another host they are refused.

SLURM runs are always submitted. ``--queue`` has no effect there (SLURM's queue holds
the job), and ``hx rerun --foreground`` and ``hx reinfer --foreground`` are refused.

sbatch options
--------------

Each run gets a batch script, saved as ``slurm.sbatch`` in its run folder:

.. code-block:: bash

   #!/bin/bash
   #SBATCH --job-name=hx-RUN_ID
   #SBATCH --output=HOME/store/PROJECT/runs/RUN_ID/logs/slurm-%j.out
   #SBATCH --no-requeue
   #SBATCH --time=08:00:00
   #SBATCH --gpus=1
   #SBATCH --partition=gpu
   #SBATCH --account=my-lab
   #SBATCH --qos=normal

   exec /path/to/python -m hypothex.cli.main --home HOME run --child RUN_ID

- ``--gpus`` is the run's GPU count (else ``slurm.gpus``); it is left out when 0.
- ``--partition`` and ``--account`` are left out when not set.
- Each item of ``slurm.extra`` becomes one more ``#SBATCH`` line.
- The compute node runs ``hx run --child`` with the same Python as the login node, so
  it uses the same install (shared filesystem).

``slurm.extra`` takes further ``sbatch`` options in ``environments.yaml``, exactly one
option token per item:

.. code-block:: yaml

   slurm:
     partition: gpu
     time: "08:00:00"
     gpus: 1
     extra: ["--qos=high", "--mem=64G", "--exclusive", "--constraint=a100"]

Hypothex refuses an item that is not exactly one token
(``"--qos=normal --mem=8G"`` is two), and an item that sets an option Hypothex owns,
in any form (long name, abbreviation, or short letter): ``--job-name`` (``-J``),
``--comment``, ``--output`` (``-o``), ``--error`` (``-e``), ``--chdir`` (``-D``),
``--wrap``, ``--requeue``, and ``--no-requeue``. Every job is ``--no-requeue``: a
second attempt cannot run the same run. Values may use letters, digits, and
``_ . : + @ / , = -`` only. ``time`` uses SLURM's formats (``MM``, ``HH:MM:SS``,
``D-HH:MM:SS``).

.. note::

   ``"-C a100"`` holds a space, so it is two tokens and is refused. Write
   ``"-Ca100"`` or ``"--constraint=a100"``.

Submission and intents
----------------------

Hypothex records an **intent** before it calls ``sbatch``: an entry in
``<home>/slurm/outbox/RUN_ID.json`` with a unique comment ``hx-RUN_ID-NONCE``, and
the event ``run.submitting``. The job is submitted with ``sbatch --parsable`` and that
``--comment``. Then:

- **Job id returned**: the run records it (``run.submitted``) and stays ``queued``
  until ``hx run --child`` starts on the node.
- **Rejected** (``sbatch`` exits non-zero with a known rejection and no job id): the
  run is ``failed`` with SLURM's message.
- **Outcome unknown** (a timeout, a signal, a garbled answer): the run stays
  ``queued`` and gets the event ``run.submit_unknown``. On each poll the env server
  looks for a job with that comment in ``squeue`` and ``sacct``. When it finds one, it
  records the job. When both commands answer without it, and 5 minutes have passed since the intent,
  the run fails.

``sacct`` can find a job by its comment only when the cluster's accounting stores job
comments (``AccountingStoreFlags`` contains ``job_comment``; older SLURM:
``AccountingStoreJobComment=Yes``). The env server checks ``scontrol show config``
once per start. Without comment accounting, an unknown submission stays ``queued``
with the reason ``submission outcome unknown; check squeue/sacct``. Check by hand and
``hx stop`` the run when the job does not exist. ``hx hosts status --json`` shows
``slurm.comment_accounting`` for each SLURM host (``null`` when not connected).

Tracking
--------

Every 30 seconds the env server polls ``squeue`` for its jobs, then ``sacct`` for
jobs that left the queue. The compute node writes only files in the run's folder
(``run.yaml``, logs, metrics, and ``exit.json``); the env server reads them and
records the run's start and end. Only the login node opens the SQLite files
(``index.db``, ``events.db``): SQLite does not work across machines on NFS, Lustre, or
GPFS.

A job that is gone without an exit record, in two polls in a row, makes the run
``lost``. The reason names SLURM's end state when ``sacct`` knows it, for example
``SLURM ended job 81234 with NODE_FAIL on node017; no exit record``.

The SLURM job's own output goes to ``logs/slurm-JOBID.out`` in the run folder.

Cancel
------

.. code-block:: bash

   hx stop RUN_ID

``hx stop`` on a SLURM run runs ``scancel JOBID``. When the job id is not known yet
(the submission is still unknown), the stop is kept and carried out once the job
appears.

Reruns
------

A rerun keeps the run's GPU count and SLURM settings: they are saved in ``slurm.json``
in the run folder.

Accounting and cost
-------------------

A SLURM run is billed for the GPUs its node reports, else for the GPUs it asked for
(SLURM reserved them). See :doc:`cost`.

HTTP route
----------

``GET /api/v1/slurm`` on an env server answers ``{comment_accounting: bool | null}``
(``null`` when the server is not a SLURM server).
