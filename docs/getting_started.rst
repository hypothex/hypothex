Getting started
===============

This page takes you from install to a first leaderboard, the web UI, an agent, and a
first remote GPU host. Each step is short; the linked pages have the details.

Install
-------

The working package is not on PyPI yet; the ``hypothex`` entry there is a name
reservation. Install from a checkout and build the web UI first. This needs
``uv`` and Bun:

.. code-block:: bash

   git clone https://github.com/hypothex/hypothex.git
   cd hypothex
   cd ui && bun install && bun run build && cd ..
   uv tool install .            # `hx` on your PATH, outside any project
   hx --version

To log from your own code with the SDK (``import hypothex``), add that checkout
to your experiment project's dependencies:

.. code-block:: bash

   uv add /absolute/path/to/hypothex

A bare ``git+https://...`` installation does not contain the built UI. The
checkout above includes it after ``bun run build``.

Hypothex keeps its data in ``~/.hypothex`` (the *home*). ``--home PATH`` or
``HYPOTHEX_HOME`` selects another home. A throwaway home is a safe place to try things:

.. code-block:: bash

   hx --home /tmp/hx-try projects

Look around with the demo
-------------------------

The demo fills an empty home with example projects and runs, so the UI has something
to show. Nothing is trained and no host is contacted.

.. code-block:: bash

   hx --home /tmp/hx-demo demo                  # seed demo projects
   hx --home /tmp/hx-demo serve                 # then open http://127.0.0.1:7777/

Add ``--with-hosts`` to also get two fake remote hosts, a GPU queue, and a sweep (see
:ref:`demo-hosts`).

Set up a project
----------------

Run these commands at the root of your repository:

.. code-block:: bash

   hx init          # write a starter hypothex.yaml (--project NAME to name it)
   hx validate      # check the schema, metric imports, datasets, and tasks

Edit ``hypothex.yaml`` to describe your datasets, versioned metrics, and tasks. See
:doc:`project_file`.

Run and inspect experiments
---------------------------

.. code-block:: bash

   hx run -t TASK -H "why this run exists" --seed 1 -- python train.py --seed '{seed}'

``hx run`` runs the command in the foreground and records the hypothesis, git commit
and uncommitted diff, dataset fingerprints, environment, logs, and scores. Hypothex
fills ``{seed}`` (and the other template variables) before the command runs. Quote the
placeholders (``'{seed}'``) so your shell passes them through unchanged;
``--seed={seed}`` also works.

For a long job, start it in the background and follow its log:

.. code-block:: bash

   hx launch -t TASK -H "why" --seed 1 -- python train.py --seed '{seed}'
   hx logs RUN_ID --follow

Then compare:

.. code-block:: bash

   hx leaderboard TASK          # seed groups ranked by the primary metric (mean +/- std)
   hx show RUN_ID               # every path: code, config, logs, predictions, checkpoint
   hx compare RUN_A RUN_B       # config and score differences

A runnable example
------------------

``examples/toy-classifier`` has three scikit-learn models and one task:

.. code-block:: bash

   cd examples/toy-classifier
   uv run python make_data.py
   git init -q && git add -A && git commit -qm init   # optional: gives exact reruns
   for s in 1 2 3; do
     uv run hx run -t toy-test -H "baseline: logreg" --seed $s -- \
       python train_eval.py --model logreg --seed '{seed}'
   done
   uv run hx leaderboard toy-test

Re-evaluate after a metric change
---------------------------------

Bump the metric's ``version`` in ``hypothex.yaml`` after you change its code, then:

.. code-block:: bash

   hx reeval --task TASK

Hypothex scores the saved predictions again with the current metric versions. Old
scores are never overwritten; new scores are appended.

Open the web UI
---------------

.. code-block:: bash

   hx serve                     # http://127.0.0.1:7777/

The UI shows the Overview (with your hosts), tasks, and runs, and updates live. See
:doc:`ui`.

Connect an agent
----------------

.. code-block:: bash

   export HYPOTHEX_AGENT=claude
   hx tasks --json

Agents use the CLI with ``--json``, the MCP server, or the skill file. See
:doc:`agents`.

Add a remote GPU host
---------------------

Keep ``hx serve`` running on your machine (the *hub*). Then add a host that you can
reach with ``ssh gpu-box`` (key login, no password prompt):

.. code-block:: bash

   hx hosts add gpu-box --ssh gpu-box --usd-per-gpu-hour 2.10
   hx hosts map toy-classifier gpu-box /home/me/code/toy-classifier
   hx hosts status
   hx launch --host gpu-box --gpus 1 --queue -t toy-test -H "rf on the GPU box" \
       --seed 1 -- python train_eval.py --model rf --seed '{seed}'

Next: :doc:`remote`, :doc:`gpus`, :doc:`slurm`, :doc:`sweeps`, and :doc:`cost`. If
something does not work, see :doc:`troubleshooting`.
