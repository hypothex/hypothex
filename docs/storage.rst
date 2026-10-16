Storage and cleanup
===================

Hypothex reports allocated bytes for run folders, recorded artifacts and local
pulled copies. It counts symlinks themselves and never follows them during a
measurement walk. Directory allocation is excluded; file allocation uses
``st_blocks * 512`` where available, otherwise ``st_size``. Totals describe the
reported entries; shared or nested recorded artifacts can overlap.

.. code-block:: bash

   hx storage report --local-only
   hx storage clean --archived --older-than 30d --dry-run
   hx storage clean --apply cp-0123abcd

The last command prompts for the exact integer byte total from the plan. A
rounded GB value is not confirmation. Plans default to a 60-minute lifetime,
are stored privately under ``<home>/storage/plans/``, and can be applied once.
An incorrect confirmation leaves the plan available; expiration removes it.

Eligibility and protection
--------------------------

Cleanup requires an archived, unstarred, terminal run whose end time satisfies
the selected age limit. By default it selects checkpoint artifacts and pulled
copies. Other artifact kinds can be selected explicitly. Run records, scores,
predictions, metrics, logs, source captures and other run metadata stay protected;
only contents of ``artifacts/`` and ``pulled/`` inside a run folder are eligible.
The filesystem root, user home, Hypothex home/store, registered repositories and
their ancestors are protected. These checks cover both literal and resolved
home/store spellings, including a home below a symlinked parent.

An artifact shared with an ineligible run is retained, including overlapping
folder artifacts and checkpoint inputs. Local pulled copies also protect their
owning run, including mirrored runs: excluding pulled copies from cleanup does
not remove their ownership protection. These owners are read again under the
cleanup lock at apply time. Relative checkpoint inputs are interpreted against
the reader's recorded working directory. Cleanup reads current run files,
including records not yet indexed. Unknown or unreadable ownership metadata
prevents deletion. Each host checks its own paths before a remote candidate is
planned and again when deletion is requested. An unavailable host check refuses
the candidate. Failure to reach one host during apply does not stop other hosts.

Refusals identify dependencies as ``used by <run>`` and modified artifacts as
``changed since plan``. Cleanup is admin-only and never through MCP: agents can
inspect storage and produce a plan, while a person confirms its application.

Every deletion rechecks age, ownership, environment, protection, byte count and
modification time. A changed item is skipped. The cleanup lock also coordinates
run creation with checkpoint inputs, starring and archiving. Independent filesystem
writers are handled with no-follow directory descriptors: removal uses a pinned
parent, verifies node identity again after measurement, and never falls back to
absolute-path deletion. Missing platform capabilities and inaccessible paths
are skipped without reporting freed bytes or writing cleaned markers.

On Linux, ancestor traversal uses ``O_PATH``; on macOS/BSD it uses ``O_SEARCH``
where available. The conservative ``O_RDONLY`` fallback can refuse ancestors
that permit traversal but cannot be listed. Directories being measured or removed
must still be readable. A final symlink artifact is unlinked without deleting its
target.

Deletion records
----------------

Successful deletions append to ``<run_dir>/.hx/cleaned.json`` and emit
``run.artifacts_cleaned``. Applying a plan emits ``storage.cleaned``. Cleanup
never rewrites ``run.yaml`` or changes run status.

Each cleaned marker identifies the deletion filesystem with ``environment_id``
and retains the raw path. A local pulled copy of a remote run belongs to the
local environment. Host deletion results retain the host's environment when
mirrored on the hub. Identical path strings in two environments remain distinct.
Legacy markers without an environment have unknown location and must not be
used to infer deletion in another environment.

Python usage
------------

.. code-block:: python

   from hypothex.core.settings import StorageSettings
   from hypothex.core.storage import CleanPolicy, apply_clean, plan_clean

   proposed = plan_clean(
       ctx, None, CleanPolicy(older_than_days=30),
       created_by="human:sv", settings=StorageSettings(),
   )
   # Inspect proposed.items and proposed.refused before confirming.
   result = apply_clean(
       ctx, None, proposed.plan_id,
       confirm_bytes=proposed.total_bytes, actor="human:sv",
   )

Inspect ``deleted``, ``skipped`` and ``errors`` in the result; a completed apply
can include refusals. ``freed_bytes`` covers only successfully removed items.

.. automodule:: hypothex.core.storage
   :members: measure_path, local_usage, storage_report, plan_clean, apply_clean,
             check_artifacts, delete_artifacts, cleaned_artifacts, cleanup_lock
