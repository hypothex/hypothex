Paper baselines and table exports
=================================

Published baselines
-------------------

Add published measurements to a task in ``hypothex.yaml``. References without a
key, such as ``accuracy``, mean ``accuracy/value``.

.. code-block:: yaml

   tasks:
     classify:
       dataset: testset
       metrics: [accuracy, latency]
       primary: accuracy
       baselines:
         - name: Example paper
           values: {accuracy: 0.91, latency/p95: 440.0}
           std: {accuracy: 0.01}
           source: arXiv:2401.01234
           metric_version_equivalent: {accuracy: v2, latency: v1}
           note: Published test split

Sources accept an ``arXiv:`` identifier, ``doi:`` identifier, or HTTPS URL.
Values and standard deviations must be finite, and every standard deviation
must have a corresponding value. Baseline names must be unique within a task.
An equivalence string, instead of a mapping, declares that version for every
metric of the task. An omitted equivalence never counts as a version match.

Baselines appear after seed groups. They never contribute to ranking, best
markers, seed counts, statistical comparisons, or candidate selection. The
leaderboard includes their normalized values, source links, version matches,
and primary-score delta. A positive delta means the best ranked group beats
the paper in the primary metric's direction. A missing selected key or missing
ranked primary score leaves the delta unset.

Create a table
--------------

The core API builds a numeric table before rendering it. This separates data
selection from presentation and makes repeated exports deterministic.

.. code-block:: bash

   hx export my-project/classify --format latex --noise both -o table.tex
   hx export my-project/classify --primary latency/p95 --format markdown
   hx export --runs run-a,run-b --format csv

Task exports default to the configured primary. ``--primary`` changes ranking
and the primary test-set interval without changing explicitly selected columns.
Run comparison exports reject ``--primary``.

.. code-block:: python

   from hypothex.core.context import Context
   from hypothex.core.export import ExportOptions, export_task, task_table

   ctx = Context.open()
   options = ExportOptions(
       format="latex",
       primary="latency/p95",
       metrics=["accuracy", "latency/p95"],
       noise="both",
       percent=True,
       standalone=True,
       caption="Classification results",
       label="tab:classification",
   )
   table = task_table(ctx, "classify", "my-project", options)
   text = export_task(ctx, "classify", "my-project", options)

``primary`` selects the task's ranking metric and its test-set interval. If
omitted, the configured primary is used. ``metrics`` selects the displayed
columns independently. Otherwise the selected primary is first, followed by
other recorded keys in sorted order. ``groups`` accepts group IDs or labels;
``top`` limits the selected groups. ``baselines=False`` omits paper rows.

Directions come from the same per-key rule used by the leaderboard: explicit
``higher_is_better: true`` or ``false`` wins. Only an unset direction on a
``system_bench`` percentile defaults to lower-is-better. Other unset directions
default to higher-is-better.

Percent scaling is independent for each column. Only unitless fraction
columns scale by 100, including their mean, standard deviation, interval, and
paper values. Latency remains in its original units. Task-table footnotes name
the scaled columns. Callers building a table directly with
``leaderboard_table`` can supply ``directions`` and ``value_formats`` mappings;
unless supplied, only the primary uses the board's format and secondary
columns are treated as numbers.

Noise and marks
---------------

``noise`` accepts ``both``, ``seed``, ``test``, or ``none``. Seed noise appears as
``mean ± std``. Identical seeds show ``◇×n`` instead of
zero standard deviation. Single-seed groups get ``¹``. Test-set intervals
appear only on the selected primary, when available, as ``[lo, hi]`` with the
method identified in a footnote. Missing noise evidence stays missing.

The best group mean in each displayed column is bold; ties are all marked.
``†`` denotes a group within noise of the best, and ``mark_noise=False`` hides
that display mark. ``‡`` denotes a paper result whose shown metric version
does not match. Baselines are never bolded as best.

Formats and comparisons
-----------------------

``format`` accepts ``markdown``, ``latex``, and ``csv``. Markdown and LaTeX use
fixed ``digits`` (0 through 6); missing values appear as an em dash or ``--``.
LaTeX requires ``\usepackage{booktabs}``; ``standalone=True`` wraps the tabular
in a table with caption, label, and footnotes. Text is escaped for LaTeX.
Markdown table delimiters and line breaks in labels are escaped. CSV uses
long format, full floating-point precision, empty missing fields, and standard
CSV quoting. Every format ends with one newline.

.. code-block:: python

   from hypothex.core.export import export_compare

   csv_text = export_compare(
       ctx,
       ["run-a", "run-b"],
       ExportOptions(format="csv", metrics=["accuracy", "latency/p95"]),
   )

Comparisons accept 2 through 20 run IDs, preserve their order, and use each
project's current metric versions. Each row is one run with no seed or
test-set noise. Shown metrics with conflicting versions or effective
directions are refused. ``primary`` is only for task exports; both comparison
entry points reject it. Comparison percent scaling also applies per column.

API reference
-------------

.. automodule:: hypothex.core.export
   :members: ExportOptions, ExportCell, ExportRow, ExportTable, leaderboard_table,
             compare_table, task_table, export_task, export_compare, render,
             latex_escape, fmt_number
