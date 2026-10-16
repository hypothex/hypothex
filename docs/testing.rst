Testing without real services
=============================

Run the test suite with ``uv run pytest``. Tests use local fakes and disposable
homes. They must never contact a real SSH host, SLURM cluster, Slack workspace,
SMTP server, Tailscale tailnet, model provider, or external PostgreSQL server, or
read or write ``~/.ssh``. Docker integration tests are opt-in with ``-m docker``;
PostgreSQL integration uses a throwaway local container, not a lab database.

``tests/conftest.py`` installs isolation before test modules and session/module
fixtures run, then reinstalls it before each test. Python socket connections and
DNS lookups refuse external addresses. SSH, GPU, SLURM, and Tailscale commands
point to refusing stubs until a test explicitly installs a fake. The inherited
Slack webhook, SMTP password, index password, and hub token are removed.

Local fixture settings
----------------------

Bind fake HTTP and SMTP listeners to ``127.0.0.1`` and port ``0`` to allocate a
local ephemeral port. Use synthetic credentials, a temporary Hypothex home, and
explicit fixture settings. PostgreSQL uses libpq, so its two synchronous
connection APIs have a separate guard. Pass the container's loopback address,
allocated port, database, user, and synthetic password explicitly::

    psycopg.connect(
        host="127.0.0.1",
        port=container_port,
        dbname="hypothex_test",
        user="hypothex_test",
        password="synthetic-test-password",
    )

All inherited ``PG*`` variables are removed at session and test setup. Any
``PG*`` variable added later, including one with an empty or local value, blocks
PostgreSQL connections. Service selection is refused. Every host and hostaddr
in a multihost configuration must be local; localhost aliases are pinned to
numeric loopback addresses. Missing or empty host entries use ``/tmp`` as the
intentional test-only Unix socket directory. Explicit absolute socket
directories are preserved. Unspecified PostgreSQL TCP addresses are refused.
These restrictions belong to the test harness, not production configuration.

When launching a child process, scrub the final environment after all scenario
overrides so inherited defaults cannot reappear::

    from tests.fakes.network import pg_child_environment

    child_env = pg_child_environment({**os.environ, **scenario_overrides})
    subprocess.run(command, env=child_env, check=True)

The helper retains non-PG values, including explicit synthetic fixture settings,
and does not mutate either input mapping. Python monkeypatches do not propagate
into arbitrary child processes: pytest children install their own hooks, while
other children require explicit local/fake configuration. Do not change process
environment concurrently with PostgreSQL connection attempts.

Guard regression checks
-----------------------

Run the focused checks with::

    uv run pytest tests/test_isolation.py tests/test_network_guard.py

The PostgreSQL matrix uses the imported ``tests.fakes.network`` implementation
and real psycopg parsing/preprocessing. It installs an inert
``Connection._connect_gen`` boundary plus socket/DNS tripwires before attempting
connections. Forbidden cases must reach zero driver boundaries; accepted cases
record numeric loopback or local Unix destinations and immediately raise a
private sentinel. Service-default diagnostics only read disposable synthetic
service files. These tests never open a database connection and do not replace
Docker PostgreSQL acceptance tests. A disposable pytest child verifies both
session scrubbing and removal of defaults deliberately left by a preceding test.
