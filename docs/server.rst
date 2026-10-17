PostgreSQL index
================

SQLite is the default index and needs no migration commands. A server can use
PostgreSQL for its index while keeping run folders, the event log, command
receipts, and authentication state under the same Hypothex home. The run files
remain the source of truth.

Setup
-----

Install the PostgreSQL driver extra::

   uv tool install '.[server]'  # from a checkout with its UI built

Create an empty PostgreSQL database with a role permitted to create tables and
indexes. Set the password in the server environment, then configure
``<home>/config.yaml``::

   server:
     index_url: postgresql+psycopg://hypothex@127.0.0.1:5432/hypothex
     index_password_env: HYPOTHEX_INDEX_PASSWORD

The URL must not contain a password, including query-string password parameters.
The configured variable can also be resolved from the home's private
``secrets.env`` file. Passwords are passed to the database driver and never
written into Alembic configuration options.

Before starting the server, apply migrations::

   hx db upgrade
   hx db current --json
   hx reindex

``hx db upgrade`` installs the Alembic head, currently ``0001_phase3`` (index
schema version 5). ``hx db current`` reports the installed revision, or ``null``
in JSON output before the first upgrade. Both commands read settings directly,
so they work before the normal context can open the index. SQLite rejects these
commands because it rebuilds its disposable index automatically.

Every context open reads ``config.yaml``. Invalid settings stop the command;
they do not silently select SQLite or disable authentication. A PostgreSQL
schema at another revision requires ``hx db upgrade``. An unavailable database
produces ``IndexUnavailableError``; database outages during API requests produce
HTTP 503 with a secret-free error message.

Rebuilds and recovery
---------------------

``hx reindex`` rebuilds indexed projects, runs, tags and scores from files.
Metric histories remain deferred until queried, preserving bounded live reads
and exact terminal histories. Run names, owners, parents, score provenance,
mirror cursors, and stale-score recovery markers survive rebuilding.

Both backends publish atomically: concurrent readers see the old or new index,
and changes committed during staging are retained. SQLite stages into a unique
local database. PostgreSQL stages into transaction-local temporary tables, then
uses database advisory locks to serialize final catch-up and publication with
ordinary index writes. Writers continue during staging; a failed publication
rolls back and releases its transaction locks.

Run mutations write files before the index. If a database connection fails,
the affected run ID is appended to ``<home>/index-pending.txt``. On the next
context open and during the server's periodic repair, Hypothex re-reads each
run under its run lock and repairs its index entries. Deleted run folders cause
the indexed entries to be removed. Repair claims have names such as
``index-pending.txt.0123abcd.claim``; interrupted claims remain available for the
next repair and are removed only after every claimed run has been processed.

The index cache uses a PostgreSQL connection-lifetime identity and database
generation. Reconnecting, rebuilding, or renaming a run invalidates derived
leaderboards and run-name caches without requiring a local SQLite path.
