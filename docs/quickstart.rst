Quickstart
==========

Install
-------

.. code-block:: bash

   uv add hypothex

Add Hypothex as a dependency of your project.

.. code-block:: bash

   uv tool install hypothex

Or install ``hx`` as a standalone tool, outside any particular project's virtualenv.

Set up a project
-----------------

.. code-block:: bash

   hx init

Write a starter ``hypothex.yaml`` in the current directory; edit it to describe your
datasets, metrics, and tasks.

.. code-block:: bash

   hx validate

Check the schema, that every metric function imports, and that every task's dataset
and metric exist.

Run and inspect experiments
----------------------------

.. code-block:: bash

   hx run -t TASK -H WHY --seed N -- CMD {seed}

Run ``CMD`` in the foreground, recording the hypothesis, git commit, dataset
fingerprints, environment, logs, and scores. ``{seed}`` (and other template
variables) are filled in before the command runs.

.. code-block:: bash

   hx leaderboard TASK

Rank seed groups of a task by the primary metric (mean +/- std over seeds).

.. code-block:: bash

   hx show RUN_ID

Show everything about one run, including where every file (code, config, logs,
predictions, checkpoint) lives.

Re-evaluate after a metric change
-----------------------------------

Bump the metric's ``version`` in ``hypothex.yaml`` after changing its code, then:

.. code-block:: bash

   hx reeval --task TASK

Re-score saved predictions with the current metric versions; old scores are never
overwritten, only appended to.
