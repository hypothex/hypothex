Cost tracking
=============

Hypothex adds up what each run cost: GPU time at the host's price, plus API spend
that the run logs. Cost shows in the run's record, on leaderboard rows, on sweeps, in
the Overview, and per host (the UI's Hosts panel shows cost today).

Set a price
-----------

Give each host its price per GPU hour:

.. code-block:: bash

   hx hosts add gpu-box --ssh gpu-box --usd-per-gpu-hour 2.10

Or set ``usd_per_gpu_hour`` on the host in ``~/.hypothex/environments.yaml``. A host
without a price counts GPU hours but no GPU dollars. The price lives only on the hub:
env servers do not know it, and the hub prices each run that it copies from a host.
Runs on the hub machine itself have no GPU price, so their cost is their API spend.

How it is computed
------------------

For a run that has ended:

.. code-block:: text

   gpu_hours = wall hours x GPUs
   gpu_usd   = gpu_hours x usd_per_gpu_hour      (0 without a price)
   api_usd   = the sum of usd in usage.jsonl
   total_usd = gpu_usd + api_usd

- Wall hours are ``ended_at - started_at``. A run that has not started or not ended
  costs 0 so far.
- GPUs are the GPUs the run held. A SLURM run whose node did not report GPU indices is
  billed for the GPUs it asked for, because SLURM reserved them.
- Example: 90 minutes on 2 GPUs at 2.10 USD, plus 0.375 USD of API calls, gives
  ``gpu_hours=3.0``, ``gpu_usd=6.3``, ``api_usd=0.375``, ``total_usd=6.675``.

The result is saved as ``cost`` in the run's ``run.yaml``:
``{gpu_hours, gpu_usd, api_usd, total_usd}``.

Log API spend
-------------

Log each model call from your code with the SDK. Rows go to ``usage.jsonl`` in the run
folder and are summed when the run ends:

.. code-block:: python

   import hypothex as hx

   run = hx.current()
   run.log_usage(tokens_in=4410, tokens_out=512, usd=0.0131, seconds=4.8, example_id="ex-1")

Where cost shows
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Place
     - What
   * - Run (``hx show RUN_ID --json``)
     - ``record.cost``
   * - Leaderboard row (``hx leaderboard TASK --json``)
     - ``cost``: the sum over the seed group's runs (``null`` when no run has a cost
       yet)
   * - Sweep (``hx sweep show ID``)
     - ``total_usd`` of all the sweep's runs
   * - Overview (``GET /api/v1/overview``)
     - ``cost_usd`` (runs in the window) and ``cost_today_usd`` (runs that ended today)
   * - Hosts (``hx hosts status``)
     - ``cost_today_usd`` per host, and the host's ``usd_per_gpu_hour``

"Today" starts at local midnight on the hub. A run counts on the day it ended, however
long ago it started.
