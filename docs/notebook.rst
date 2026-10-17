Lab notebook
============

Each project has a Markdown notebook stored in
``<home>/store/<project>/notebook/YYYY-MM-DD.md``. These files remain available
when the index is rebuilt and are not mirrored to remote hosts.

Entries and run links
---------------------

Append an entry to the hub's current day with::

   hx note --project toy "Try the smaller model after [[run:baseline]]"

An explicit ``--day YYYY-MM-DD`` chooses another day. Otherwise the hub uses
``digest.timezone`` from ``config.yaml``, or its machine's timezone when unset.
Each entry records its timestamp and author. ``[[run:<id>]]`` links resolve to
run status, a short hypothesis label and the newest valid score of the task's
current primary metric. Unknown run IDs remain visible as unresolved links.

In Python, the same core API accepts a registered project::

   from hypothex.core.context import Context
   from hypothex.core.notebook import append_entry, read_day

   ctx = Context.open()
   saved = append_entry(ctx, "toy", "Compare [[run:baseline]]", "human:alice")
   current = read_day(ctx, "toy", saved.day)

Concurrent editing
------------------

Appending entries serializes writes under the project lock. A whole-day edit
must include the ``hash`` from the version the editor read. If another writer
changes the file first, saving raises ``NotebookConflictError`` and supplies the
current day, so the editor can preserve both versions. An empty save clears the
day. Each day is limited to 1 MiB of UTF-8 content, including entry headings and
newlines; rejected writes leave the previous content intact.

Both append and replace operations emit ``notebook.updated`` with the project,
day and author. Notebook text is a file of record; deleting or rebuilding the
SQL index does not delete notes.
