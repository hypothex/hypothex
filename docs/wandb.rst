W&B local logs and exported history
===================================

Import completed Weights & Biases run logs and exported histories without a W&B
account or API key. Binary logs need Hypothex's optional reader dependency:

.. code-block:: console

   uv tool install 'hypothex[wandb]'

From a source checkout, use ``uv sync --extra wandb`` and prefix commands with
``uv run --extra wandb``.
CSV, JSONL and JSON exports work with the base installation, without the W&B SDK.

Import a run
------------

In a project containing ``hypothex.yaml``, import a binary run log or its containing
run folder:

.. code-block:: console

   hx import wandb ./wandb/offline-run-20261022_120000-abc123/run-abc123.wandb
   hx import wandb ./wandb/offline-run-20261022_120000-abc123 --task training
   hx import wandb /data/run-abc123.wandb --repo /code/my-project --json
   hx runs
   hx serve

``--task`` is optional and must name a task in the destination project. A folder
must contain exactly one ``.wandb`` file directly inside it; pass individual run
folders when importing multiple experiments. The command writes to the local
Hypothex home (``--home`` / ``HYPOTHEX_HOME``), even when a hub is configured.

The imported run appears in the existing runs list and metrics charts. Numeric
history entries retain their names, W&B ``_step`` and ``_timestamp``; nested keys
use ``/`` separators. Booleans, nonfinite values, media, strings, and internal
keys starting with ``_`` are omitted from scalar curves. When ``_step`` is absent,
the protobuf step is used, or the zero-based history row number if neither exists.
Full scalar history is kept in ``metrics.jsonl``. Import initially indexes up to
1,000 points for each of the first 256 metric names, with additional rows counted
in provenance. An index rebuild uses Hypothex's normal history indexing policy.
JSON step values in binary logs and exports retain exact integer precision;
fractional steps and steps outside the signed 64-bit range are rejected.

The run name, tags and configuration are retained. Display names are shortened
to 80 characters and line breaks become spaces; the original name is preserved.
Configuration hashes ignore the top-level ``seed``, so otherwise identical
configurations share a seed group. The original seed remains in the saved config.
Integer seeds also populate the native seed field, so reruns with the same seed
count as one sample. Other seed values remain in configuration without coercion.
``env/wandb.json`` in the
imported run folder records its original W&B identity, source file hash and path,
summary values, and point counts. Summary values are provenance, not evaluated
Hypothex scores. A W&B exit code of zero produces a finished run; a nonzero code
produces a failed run. End time is the last available history timestamp, bounded
below by start time; it is not a measured process-exit timestamp.

Import behavior
---------------

The source is read without modification. Identical file bytes imported into the
same format, project and task return the existing run, even if the file moved. Changed
file bytes create a separate historical snapshot. Imported runs carry no executable
command or source artifact links.
Repeat imports still snapshot and hash the source to verify its identity, then
reuse the published run and its saved point count without decoding or writing
the metric history again. Older or damaged point-count provenance falls back
to parsing the source. Interrupted index writes retain normal index recovery
when the home is reopened.

Finish the W&B run before importing it. Missing exit records, truncated records,
invalid checksums and unsupported file versions fail before a run is published.
The binary reader supports version-0 W&B local datastore files and limits each
logical record to 64 MiB. Cloud downloads, live tailing, console/debug logs,
artifact files and media are not imported by this command.

Exported history
----------------

Use the same command for CSV, JSONL or JSON history exported from W&B:

.. code-block:: console

   hx import wandb history.csv --repo /code/my-project
   hx import wandb wandb-history.jsonl --repo /code/my-project --task training
   hx import wandb history.json --repo /code/my-project --json

Each file imports as one historical snapshot. Its display name comes from the
filename; original run config, tags, identity and process exit status cannot be
recovered from history alone. A snapshot's ``finished`` state means the import
completed, not that the original training process finished successfully.
``env/wandb.json`` marks these imports with ``snapshot: true``.

Supported layouts:

* CSV with a header row and one history step per row, such as a DataFrame history
  export. ``_step`` selects the step axis; ``Step`` is accepted when ``_step`` is
  absent. A leading blank or ``Unnamed: 0`` pandas index column is ignored.
  Blank cells are skipped. Chart exports with several run-prefixed metric columns
  keep those column names together in one snapshot; they do not create separate runs.
* JSONL with one history object per nonblank line, such as saved
  ``scan_history()`` rows or a legacy ``wandb-history.jsonl`` file.
* JSON containing an array of history row objects. Column-oriented objects and
  W&B Table artifacts are not history exports and are not accepted.

For example, these JSONL rows import ``loss`` and ``val/accuracy`` at steps 4 and 8:

.. code-block:: json

   {"_step": 4, "_timestamp": 1700000000, "loss": 0.75, "val": {"accuracy": 0.5}}
   {"_step": 8, "_timestamp": 1700000001, "loss": 0.25}

Nested JSON metric objects use ``/`` names. Objects with ``_type`` (media), lists,
booleans, strings and nonfinite numbers are excluded. If no step is supplied, the
zero-based row number is used. Only data present in the export can be imported;
sampled exports remain sampled. Run-summary CSVs are not time-series histories.

CSV and JSONL are streamed with a 64 MiB logical-row limit. JSON arrays are limited
to 64 MiB for the whole file. Malformed rows, duplicate CSV headers, invalid steps,
and exports with no finite scalar metrics fail before a run is published.
