Sweeps
======

A sweep runs every combination of a parameter grid once per seed, as one group.
``hx sweep show`` gives a table of the parameters against the task's primary metric,
the best cell, progress, and cost.

Start a sweep
-------------

.. code-block:: bash

   hx sweep -t TASK -H "lr x beam" --grid lr=1e-4,3e-4,1e-3 --grid beam=5,10 \
       --seeds 3 --host gpu-box --gpus 1 --queue -- \
       python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'

This starts 3 x 2 x 3 = 18 runs. ``hx sweep ...`` with options is short for
``hx sweep create ...``.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Meaning
   * - ``-t``, ``--task``
     - The task that scores the runs (optional).
   * - ``-H``, ``--hypothesis``
     - Why the sweep exists; copied onto each run. Agents must give one.
   * - ``--grid name=v1,v2``
     - One grid parameter (repeatable).
   * - ``--random N``
     - Random search: ``N`` samples (see below).
   * - ``--param name=low:high[:log]``
     - A range that ``--random`` samples from (repeatable).
   * - ``--seeds``
     - A count (``3`` means seeds 1, 2, 3) or a list (``1,2,5``). Default ``3``.
   * - ``--host``
     - Run on this host. Without it, the sweep runs on this machine.
   * - ``--gpus N``
     - GPUs for each run.
   * - ``--queue``
     - Wait in the host's queue for GPUs.
   * - ``--repo``
     - The project repo (default: the current folder).
   * - ``--json``
     - Print the sweep summary as JSON.

Rules:

- The command must use every swept name as ``{name}``. A name that the command does
  not use, or a ``{field}`` that no parameter or built-in fills, is refused.
- Each run gets its seed as ``{seed}`` and as ``$HYPOTHEX_SEED``.
- A sweep has at most 1000 runs.
- Seed 1 of every combination starts first, then seed 2, and so on. A queue then
  fills the whole table early.
- With ``--host``, the CLI sends your commit and uncommitted diff, as for
  ``hx launch --host`` (see :doc:`remote`).

Random search
-------------

.. code-block:: bash

   hx sweep -t TASK -H "lr search" --random 20 --param lr=1e-5:1e-3:log \
       --grid beam=5,10 --seeds 2 -- python train.py --lr '{lr}' --beam '{beam}' --seed '{seed}'

With ``--param`` ranges, ``--random N`` draws ``N`` samples once and crosses them
with every grid combination, so each grid cell sees the same samples. ``:log`` samples
on a log scale (``low`` must be above 0). Without ranges, ``--random N`` keeps ``N``
grid combinations chosen at random. The samples come from the sweep id, so a sweep
keeps the same samples for its whole life (``extend`` too).

Follow a sweep
--------------

.. code-block:: bash

   hx sweeps                            # newest first, with the best cell
   hx sweeps -p toy-classifier --json
   hx sweep show s-7f3a                 # progress, params x primary metric, best, cost
   hx sweep show s-7f3a --json

``hx sweep show`` prints one row per combination: the parameters, ``n`` (scored
seeds), the mean, the 95% interval, and a ``best`` mark. The interval is over the test
set when the runs log per-example scores, else over seeds.

The JSON summary has ``spec`` (the definition), ``counts`` (runs by status),
``cells`` (one per combination: ``params``, ``group_id``, ``n``, ``mean``, ``lo``,
``hi``, ``std``, ``run_ids``, ``runs``), ``best``, ``headline``, ``total_usd``,
``run_ids`` (launch order), and ``tag``.

Change a sweep
--------------

.. code-block:: bash

   hx sweep extend s-7f3a --seeds 4,5   # add runs for every combination x seeds 4, 5
   hx sweep cancel s-7f3a               # stop queued runs; running runs keep going

``extend`` is safe to repeat: seeds that are already in the sweep start only the runs
that are missing. If a host drops during a launch, the sweep keeps the runs that
started; ``hx sweep extend`` with the same seeds then starts only the missing ones.
``--seeds 4`` adds seed 4 (here a single number is a seed, not a count).

``cancel`` stops the runs that wait in the queue; they end as ``killed``.

``show``, ``extend``, and ``cancel`` take ``-p PROJECT`` when two projects have a
sweep with the same id.

Where sweeps live
-----------------

- The definition is saved at ``<store>/<project>/sweeps/<id>.yaml`` on the machine
  that launched it (normally the hub). Sweep ids look like ``s-7f3a``.
- Membership is a tag, never a stored list: each run gets the tag
  ``sweep:<hub>:<id>``. ``<hub>`` is the first 8 characters of the hub's environment
  id, so two hubs that use one host never mix their sweeps. Read the tag from the
  summary's ``tag`` field; do not build it yourself.

.. code-block:: bash

   hx runs --tag "$(hx sweep show s-7f3a --json | jq -r .tag)"

HTTP and MCP
------------

Routes: ``POST /api/v1/sweeps``, ``GET /api/v1/sweeps/{id}``,
``GET /api/v1/sweeps/{project}/{id}``, ``GET /api/v1/projects/{project}/sweeps``,
``POST /api/v1/sweeps/{project}/{id}/cancel_queued``, and
``POST /api/v1/sweeps/{project}/{id}/extend``. See :doc:`http_api`.

MCP tools: ``launch_sweep``, ``get_sweep``, ``cancel_sweep``, ``extend_sweep``. See
:doc:`mcp`.
