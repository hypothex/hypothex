A hub for a small lab
=====================

One hub serves a few people. Turn auth on, pair each device once, and everyone sees
the same projects, tasks, runs, sweeps, hosts, and notebooks. There are no passwords:
a device is paired with a one-time link.

Turn auth on
------------

.. code-block:: yaml

   # ~/.hypothex/config.yaml
   server:
     auth: on                       # or: hx serve --auth
     public_url: https://hub.tail1234.ts.net

``hx serve`` then makes you the owner (``admin``) and writes a session for this
machine's CLI into ``~/.hypothex/serve/server.json`` (readable only by you).

``config.yaml`` and every token file are written with mode 0600, and their folder, the
Hypothex home, is set to 0700 on each write. A home that other accounts must read (one
shared lab account) is not supported: give each person their own account and pair them.

Commands that open a home validate ``config.yaml``. Invalid settings stop the
operation with a redacted error; they never silently disable authentication or
replace a configured Postgres index with SQLite. Fix the file before retrying.

Pair a device
-------------

.. code-block:: bash

   hx pair --new-user --user alice --scope launch    # prints a QR code and a link (5 min)
   hx login 'https://hub.tail1234.ts.net/pair#p_...' # on alice's laptop
   hx whoami

A browser opens the link and gets a cookie; the CLI keeps its token in
``~/.hypothex/auth/hub-tokens.json``. The secret is after ``#``, so it is never sent
in a request line or logged. A link works once, for 5 minutes, and dies after 5 wrong
tries. Pairing never gives more than the person who made the link holds.

Scopes and ownership
--------------------

``read`` sees everything. ``launch`` also launches, reruns, tags, notes, edits the
notebook, and exports. ``admin`` also manages users, sessions, notifications, and
storage. Every run has an ``owner``: only the owner or an admin may stop, archive, or
cancel it. With auth on, the hub records who made each run (``human:alice``,
``agent:claude@alice``); a request cannot claim to be someone else.

A run executes as the Unix user of the machine that runs it, and can read everything
that user can, the hub owner's token in ``serve/server.json`` included. So runs on the
hub's own machine need admin; ``launch`` collaborators launch on hosts. Run each shared
host under its own account, never the hub owner's: everyone who launches there shares
that account.

.. code-block:: bash

   hx runs --owner me --json
   hx sessions list            # yours; --all for everyone (admin)
   hx sessions revoke s_0123456789ab
   hx users list && hx users disable bob

Reach the hub from anywhere
---------------------------

.. code-block:: bash

   hx serve --auth --tailscale

``tailscale serve`` publishes the hub over HTTPS on your tailnet; there is no other
relay. ``--tailscale`` needs auth on and binds ``127.0.0.1``.

A lab server as a host
----------------------

Run ``hx serve --auth`` on the lab server, then pair the hub with it:

.. code-block:: bash

   hx pair --client host --scope admin                 # on the lab server
   hx hosts add lab --url https://lab.tail1234.ts.net
   hx hosts pair lab 'https://lab.tail1234.ts.net/pair#p_...'   # on the hub

Only an ``admin`` link can be redeemed as a host (a host session vouches for who launched
each run). ``hx hosts pair`` refuses a link whose URL is not the host's, and the token is
only ever sent to the URL it was paired at: point ``lab`` somewhere else and the hub stops
sending it. ``token_env: LAB_TOKEN`` in ``environments.yaml`` is the other way to give the
hub a token. When the lab server stops accepting the hub, the host shows
``auth failed: hx hosts pair lab <pairing-url>`` and the hub stops retrying.

Postgres
--------

.. code-block:: yaml

   server:
     index_url: postgresql+psycopg://hx@db.lab:5432/hypothex   # never a password, not even ?password=
     index_password_env: HYPOTHEX_INDEX_PASSWORD

.. code-block:: bash

   uv tool install '.[server]'  # from a checkout with its UI built
   hx db upgrade && hx db current

Only the index moves to Postgres; run folders, the event log, and ``auth.db`` stay in
the hub's home.

Try the team demo
-----------------

Use a new disposable home to try pairing, notebook entries, notifications and
storage without a lab server::

   hx --home /tmp/hx-team-demo demo --with-team
   hx --home /tmp/hx-team-demo serve

The demo serves loopback notification sinks and a shared fake host. Its generated
project and host copy have their own matching Git history, so collaborator
launches work even when the demo home is inside another checkout. Only generated
demo repositories are initialized; an unrelated registered repository is refused.
Fresh browser pairing links are printed at startup. See :doc:`package-testing`
for testing a retained wheel in an isolated installation.
