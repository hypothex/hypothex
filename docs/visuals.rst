Agent-authored tables and charts
================================

``hypothex.visuals`` provides ``DataSource``, ``Encoding``, ``Table``, ``Chart``, and
``Dashboard``. They produce ordinary Hypothex views, so the web dashboard, CLI,
HTTP API, and MCP tools use the same saved panels.

Custom rows
-----------

An agent can compute any JSON records and save a table and chart into an existing
project/task. Replace the repository path and task below with your project.

.. code-block:: python

   from hypothex.visuals import Chart, Dashboard, DataSource, Encoding, Table

   data = DataSource(rows=[
       {"model": "small", "accuracy": 0.84, "latency_ms": 12},
       {"model": "large", "accuracy": 0.91, "latency_ms": 38},
   ])
   dashboard = Dashboard(title="Agent comparison", panels=[
       Table(title="Results", data=data,
             columns=["model", "accuracy", "latency_ms"]),
       Chart(title="Accuracy by model", data=data, mark="bar", encoding={
           "x": Encoding(field="model", type="nominal"),
           "y": Encoding(field="accuracy", type="quantitative"),
           "color": Encoding(field="model", type="nominal"),
           "tooltip": [Encoding(field="model", type="nominal"),
                       Encoding(field="accuracy", type="quantitative")],
       }),
   ])
   path = dashboard.save("/path/to/project", "train", "agent-comparison")
   print(path)

``save`` registers the repository in the selected Hypothex home, validates against
the task, and atomically creates or replaces
``.hypothex/views/train/agent-comparison.yaml``. Open the task and select that view.
Pass ``home=...`` to use a particular local home; otherwise ``HYPOTHEX_HOME`` or
the default home is used. The task must exist and ``overview`` is reserved.
An invalid definition does not replace an existing view.

Inline rows are snapshots stored in the view. Recompute and save again to refresh
them. They must be JSON objects with string keys and finite numbers: convert
DataFrames, NumPy scalars, datetimes, and other Python objects to JSON values first.
Each panel accepts at most 2,000 rows, 1 MiB of compact UTF-8 JSON, and 64 nesting
levels. Saved dashboards must also fit the existing whole-view YAML limits:
100,000 parser events and 64 nesting levels including the surrounding view
structure. These limits apply across all panels, even when each dataset fits its
own row/byte limits. Wide rows or repeated datasets can reach the whole-view limit
first; reduce rows/columns or split the content into separate dashboards. A failed
save reports the validation error and preserves the existing view.

Empty rows are valid; declare table columns to retain an empty table's
schema. ``columns=[]`` selects no columns. Row filters use exact equality or list
membership; filtering runs does not filter inline data.

The web table renders at most 50 columns, 500 rows, and 10,000 body cells per
panel. Wider tables therefore show fewer rows (for example, 200 rows for 50
columns). A footer reports the displayed and total row or column counts whenever
either is truncated. Columns retain their declared order, or their first-seen
order across all sparse rows when no columns are declared. Use ``Table(columns=[...])``
to select fields outside the displayed prefix. These display limits do not remove
saved data or schema; sorting a displayed column still considers every row.

Stored run data
---------------

Use a source to query current records each time the view is loaded. The supported
sources are ``runs``, ``scores``, ``metrics``, ``predictions``, ``samples``, ``usage``,
``traces``, and ``groups`` (see :doc:`views`). A data source contains exactly one of
``source`` or ``rows``.

.. code-block:: python

   from hypothex.visuals import Chart, Dashboard, DataSource, Encoding, Table

   dashboard = Dashboard(title="Training analysis", panels=[
       Table(title="Run settings", data=DataSource(source="runs"),
             columns=["run_id", "label", "params.lr"]),
       Chart(title="Loss by step",
             data=DataSource(source="metrics", filter={"name": "loss"}),
             mark="line", encoding={
                 "x": Encoding(field="step", type="quantitative"),
                 "y": Encoding(field="value", type="quantitative"),
                 "color": Encoding(field="run_id", type="nominal"),
             }),
   ])
   # Requires runs with a loss metric and the params.lr field.
   dashboard.save("/path/to/project", "train", "training-analysis")

``Dashboard(runs={"status": ["finished"]}, ...)`` restricts stored run sources.
Pass ``preset="training"`` to extend a preset or include existing ``PanelSpec``
objects alongside your tables/charts. ``layout={"span": 6}`` places a panel in half
of the 12-column grid.

Custom chart specifications
---------------------------

``Encoding`` accepts quantitative, nominal, ordinal, temporal, and geojson types,
plus ``aggregate``, ``title``, ``bin``, and ``time_unit``. It treats field names
literally, so a flat field such as ``params.lr`` works without manual escaping.
Use ``nested=True`` for a nested property path. Rename literal keys containing
backslashes before charting: the installed Vega-Lite compiler loses their
escaping in some transforms, so typed encodings reject them.

For layered charts, heatmaps, transforms, or other Vega-Lite features, pass
``Chart(spec={...}, ...)`` instead of ``mark`` and ``encoding``. The existing view
validation and browser loader restrictions apply: external resources and image
marks are rejected. Panel rows replace root-level spec data; nested inline datasets
remain available. Raw specs
use Vega-Lite's own field-path syntax (escape dots and brackets in literal keys).
Unknown Vega-Lite options are not fully schema-checked by the Python helpers;
the browser compiler reports invalid chart specifications.

Other submission paths
----------------------

``dashboard.to_spec()`` returns a ``ViewSpec``. ``dashboard.to_yaml()`` returns YAML
for the existing transports; serialization alone does not perform contextual
validation. With a remote hub, submit this YAML through its authenticated API or
MCP instead of calling local ``save``.

.. code-block:: python

   from pathlib import Path

   Path("agent-comparison.yaml").write_text(dashboard.to_yaml(), encoding="utf-8")

.. code-block:: bash

   hx view validate train agent-comparison.yaml --json
   hx view add train --file agent-comparison.yaml --json

MCP ``add_view`` accepts the YAML as ``text``. HTTP uses
``PUT /api/v1/tasks/{project}/{task}/views/{name}`` with ``{"text": "..."}``.
Inline data is also available directly in YAML:

.. code-block:: yaml

   title: Custom summary
   panels:
     - type: table
       title: Results
       data:
         rows: [{model: small, accuracy: 0.84}]
         fields: [model, accuracy]

Python reference
----------------

.. automodule:: hypothex.visuals
   :members:
