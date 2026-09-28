Views
=====

A view is a dashboard for one task, written as YAML: a title, an optional run filter,
and a list of panels. Each task kind ships a preset view named ``overview``; you add
your own views next to your code. Panel data is computed by the server; the UI and
agents only read rows.

Task kinds
----------

Set a task's kind in ``hypothex.yaml``. The kind picks the preset view and the run
page layout; it never changes storage or evaluation.

.. code-block:: yaml

   tasks:
     route-eval:
       dataset: routes
       metrics: [solved]
       primary: solved
       kind: agent_eval      # generic | training | agent_eval | agent_iteration | system_bench

Where views live
----------------

- **Preset**: ``overview``, from the package, one per kind.
- **Inline**: ``views:`` under a task in ``hypothex.yaml``.
- **File**: ``<repo>/.hypothex/views/<task>/<name>.yaml``. Commit these with the code.
  A file wins over an inline view with the same name. The UI editor saves files.

View names use ``a-z``, ``0-9``, ``-``, and ``_``, and start with a letter or digit.
``overview`` is reserved.

Example
-------

.. code-block:: yaml

   title: route quality
   from: agent_eval             # optional: preset panels first
   runs: {status: [finished]}   # also: tags, created_by, since
   panels:
     - type: leaderboard
       title: Best config
       data: {metrics: [solved@v2]}
       noise: [seed, test_set]
       layout: {span: 8}
     - type: scatter
       title: Cost vs score
       data: {x: usage.usd, y: solved}   # usage.usd: the run's total cost
       pareto: {x: min, y: max}
       layout: {span: 4}
     - type: markdown
       text: "Test split only; seeds 1-3."

With ``from``, the preset's panels come first; a panel whose ``title`` matches a preset
panel replaces it, and other panels are appended.

Metric references use ``name@version/key`` (version and key are optional). The
aggregates ``/mean``, ``/median``, and ``/p95`` apply to samples and per-example values.
Run usage totals are ``usage.usd``, ``usage.seconds``, ``usage.tokens_in``,
``usage.tokens_out``, and ``usage.calls``; ``usage.usd/solved`` divides a run's total by the
examples it solved on the task's primary metric (cost per success). A logged history
metric is named in full (``val/top1``). ``version`` is the task's version ordering key: the
run param ``version_param`` names (``version`` by default), or the creation time of the
group's first run when that param is missing; it works as a scatter ``x``, as a
``runs`` table field, and in a ``runs`` ``data.filter`` (``filter: {version: p10}``), also
when ``fields`` does not list it. A ``grid`` panel's ``data.y`` is a per-example field (``partial``).

Panels
------

============== ==========================================================================
Type           Shows
============== ==========================================================================
stat_strip     A row of headline numbers.
leaderboard    Seed groups ranked by the primary metric, with seed and test-set noise.
curves         Metric history by step; seeds faint, mean bold, checkpoints and spikes.
               Rows follow ``data.metrics`` order. A loss spike is one event per episode,
               labelled with its step (``spike 9k``); so is a kill (``killed 14k``).
               ``group_by: run`` draws one column per run, named ``baseline r1``.
scatter        One metric against another per group, with an optional Pareto front. A
               non-numeric ``params.``/``vars.`` x (e.g. ``v9``) is an ordinal axis in
               natural order; rows worse than the best earlier version by more than its
               95% CI are marked as regressions.
distribution   Sample distributions (ECDF) with p50, p95, p99; ``scale: log`` for latency.
               ``render: table`` draws the percentile table, with the change vs the task's
               ``baseline`` group and a 95% bootstrap CI over repeats.
grid           Items by groups; each cell is the fraction of seeds that solved the item.
table          Raw rows from a ``source`` restricted to ``fields``.
trace          The steps of one agent attempt (``data.run_id``, ``data.example_id``).
markdown       Static ``text``.
vega_lite      A Vega-Lite ``spec`` drawn over rows from a ``source``. Rows arrive inline
               only: ``url``, ``href``, ``embedOptions`` (at any depth) and ``image``
               marks are rejected.
============== ==========================================================================

Sources for ``table`` and ``vega_lite``: ``runs``, ``scores``, ``metrics``,
``predictions``, ``samples``, ``usage``, ``traces``, and ``groups``. Every row of the
per-run sources has ``run_id``,
``group_id``, ``label`` (the seed group's short name, as on the leaderboard), and
``seed``. Encode charts by ``label`` so they show config names:

.. code-block:: yaml

   - type: vega_lite
     title: Error rate
     data: {source: scores, filter: {metric: errors, key: rate}, fields: [value]}
     spec:
       mark: bar
       encoding:
         y: {field: label, type: nominal, title: null}
         x: {aggregate: mean, field: value, type: quantitative}

The ``groups`` source is task-level: one row per seed group, in version order (the
``version`` rule above; ``v9`` before ``v10``). Its keys are ``group_id``, ``label``,
``version``, ``run_id`` (latest run), ``n`` (runs), ``commit``, ``created_by``,
``hypothesis``, ``primary`` (the leaderboard mean), ``primary_lo`` and ``primary_hi``
(95% interval), ``delta_prev`` (``primary`` minus the previous group's), and ``changes``:
the ``params``/``vars`` that differ from the previous group
(``model: sonnet-5 → opus-5.5; tools: +stock_check``), else the short commit. A
``groups`` table keeps exactly the listed ``fields``:

.. code-block:: yaml

   - type: table
     title: Changes
     data:
       source: groups
       fields: [version, changes, commit, delta_prev, primary, n]

Validation
----------

A view is checked before it is saved: the schema, metric names (with a nearest-name
suggestion), sources, fields, and the Vega-Lite spec shape. Every issue has a line
number. An invalid view is never saved. YAML anchors and aliases (``&name``, ``*name``,
``<<: *name``) are not allowed, YAML may nest at most 64 levels (and hold at most 100,000
parser events), and a Vega-Lite spec may hold at most 10,000 values. Inline views in
``hypothex.yaml`` follow the same rule: an anchor or alias under ``tasks.<task>.views`` is a
config error; anchors elsewhere in the file are fine as long as they form no cycle.

.. code-block:: bash

   hx view validate route-eval view.yaml --json

.. code-block:: json

   {"ok": false, "issues": [{"line": 5, "path": "panels[0].data.metrics[0]",
     "message": "unknown metric slved", "suggestion": "solved@v2"}]}

Commands
--------

.. code-block:: bash

   hx view list TASK --json                          # overview, inline, files
   hx view show TASK NAME --json                     # info, YAML text, resolved view
   hx view init TASK --from agent_eval --name mine   # new file starting from a preset
   hx view validate TASK view.yaml --json            # check only; exit 1 if invalid
   hx view add TASK --file view.yaml --json          # check, then save as <stem>.yaml
   hx view rm TASK NAME --json                       # delete a view file

MCP tools: ``list_views``, ``get_view``, ``add_view`` (returns ``issues`` when invalid),
``query_view``.

HTTP (all under ``/api/v1/tasks/{project}/{task}``): ``GET views``,
``GET|PUT|DELETE views/{name}`` (``PUT`` body ``{text, command_id?}``; a repeated
``command_id`` returns the first result), ``POST views/validate`` (``{text}``; the
answer's ``view`` is resolved, so ``from:`` preset panels are included), and
``POST views/query`` (``{name}``, ``{view}``, or ``{panel}``).
