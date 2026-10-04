GPU status and the queue
========================

Every env server that is not a SLURM server (an SSH host, and the hub itself) knows
its GPUs and keeps a queue of runs that wait for them. A SLURM host uses SLURM's own
queue instead (see :doc:`slurm`).

GPU status
----------

The env server reads the GPUs with ``nvidia-smi``:

- ``nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total``
- ``nvidia-smi --query-compute-apps=gpu_uuid,pid``

For each GPU it reports the index, name, utilization (percent), memory used and total
(MB), the Hypothex run that holds it (``run_id``), and ``external``: true when a
process that is not a Hypothex run uses it. A host without ``nvidia-smi`` reports no
GPUs.

.. code-block:: bash

   hx hosts status                       # "gpus busy" column: busy/total per host
   hx hosts status gpu-box --json        # the full GPU list of one host

A GPU is **free** when no Hypothex run holds it and ``nvidia-smi`` shows no other
process on it.

Ask for GPUs
------------

.. code-block:: bash

   hx launch --host gpu-box --gpus 2 -t TASK -H "why" -- python train.py      # now, or refuse
   hx launch --host gpu-box --gpus 2 --queue -t TASK -H "why" -- python train.py  # wait

- ``--gpus N`` without ``--queue`` takes the lowest ``N`` free GPUs at once. When
  fewer are free, nothing starts and the error says how many are free:
  ``2 GPUs requested; 1 of 8 free; add --queue to wait for them``.
- ``--gpus N --queue`` puts the run in the host's queue. Its status is ``queued`` and
  its record shows its queue position.
- A run that asks for more GPUs than the host has is refused.
- The run's command sees only its GPUs: Hypothex sets ``CUDA_VISIBLE_DEVICES``.

``--gpus`` and ``--queue`` also work without ``--host``: the run then uses the GPUs
of the machine you launch on. The queue moves only while ``hx serve`` runs there.

How the queue moves
-------------------

The queue is **first in, first out, first fit**. Every 5 seconds the env server looks
at the runs in queue order. It starts each run whose GPU count fits the GPUs that are
free right now. A run that does not fit stays in line, and a smaller run behind it can
start first.

.. code-block:: text

   free GPUs: 3        queue: A (4 GPUs), B (2 GPUs), C (1 GPU)
   tick:     A waits (4 > 3), B starts on 2 GPUs, C starts on 1 GPU

Stop a queued run
-----------------

.. code-block:: bash

   hx stop RUN_ID

A run that waits in the queue is removed from it and ends as ``killed`` (reason
``removed from queue``). ``hx sweep cancel`` does this for every queued run of a
sweep.

HTTP routes
-----------

On an env server (send its bearer token):

- ``GET /api/v1/gpus``: ``list[GpuInfo]``, each
  ``{index, name, util, mem_used_mb, mem_total_mb, external, run_id}``.
- ``GET /api/v1/queue``: ``[{run_id, position, gpus_requested}]`` in queue order.

On the hub, ``GET /api/v1/hosts`` has ``gpus`` and ``queue`` (the queue length) for
each host. See :doc:`http_api`.

Testing without GPUs
--------------------

``HYPOTHEX_FAKE_GPUS=/path/to/gpus.json`` makes an env server read the GPUs from a
JSON list of GPU objects instead of ``nvidia-smi``. Tests and the demo use it.

.. code-block:: json

   [
     {"index": 0, "name": "Fake GPU", "util": 0, "mem_used_mb": 0, "mem_total_mb": 81920},
     {"index": 1, "name": "Fake GPU", "util": 97, "mem_used_mb": 70000,
      "mem_total_mb": 81920, "external": true}
   ]
