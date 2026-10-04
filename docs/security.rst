Security model
==============

The Hypothex API starts arbitrary commands and reads run files. So every server is
reachable only from its own machine by default, servers on shared hosts need a token,
and secrets stay out of run files.

Localhost bind
--------------

``hx serve`` binds ``127.0.0.1`` by default, on the hub and on every host. To reach a
server on another machine, use an SSH tunnel instead of a network bind:

.. code-block:: bash

   ssh -L 7777:127.0.0.1:7777 gpu-box      # then open http://127.0.0.1:7777/

A browser on your machine can still reach ``127.0.0.1``. Two checks block web pages:

- **Host allow-list**: the ``Host`` header must be ``127.0.0.1``, ``localhost``,
  ``[::1]``, or the ``--host`` address (when it is not a wildcard). Anything else gets
  ``400``. This blocks DNS rebinding.
- **Origin check**: a ``POST`` or WebSocket handshake whose ``Origin`` is not one of
  those hosts gets ``403``. A web page cannot start runs through your browser.

These checks are not authentication: any program that is not a browser can send
``Host: localhost``.

Bearer token
------------

With a token, every request except the descriptor
``/.well-known/hypothex/environment`` needs ``Authorization: Bearer <token>``. A
missing or wrong token gets ``401`` (``{"type": "AuthError"}``); a WebSocket is closed
with code ``1008``.

**Env servers** (``hx serve --kind ssh|slurm``) always have a token, because on a
shared GPU box or a SLURM login node other users can reach ``127.0.0.1`` too.

- The token is ``HYPOTHEX_SERVE_TOKEN`` when set, else a new random one for each
  start.
- It is kept in ``<home>/serve/server.json`` on the host: mode 0600, in a 0700
  folder.
- The hub reads it over ``ssh`` during the bootstrap and sends it through the tunnel.
  It is never written to ``environments.yaml`` or to error messages.
- ``hx serve`` removes ``HYPOTHEX_SERVE_TOKEN`` from its environment at start, so the
  runs it starts never inherit it.
- ``--no-auth`` drops the token. Use it only for test hosts.

**The hub's own server** (the UI on your machine) needs a token only when
``HYPOTHEX_SERVE_TOKEN`` is set. ``hx serve`` refuses a non-loopback ``--host`` (such
as ``0.0.0.0``) without one:

.. code-block:: bash

   HYPOTHEX_SERVE_TOKEN=$(openssl rand -hex 24) hx serve --host 0.0.0.0

Clients find the token like this:

- ``hx`` and ``hx mcp`` send ``HYPOTHEX_HUB_TOKEN`` when it is set.
- Else, for a hub on a loopback address, they read the token from that hub's
  ``<home>/serve/server.json`` (only when its port matches). A token is never read from
  that file for a hub on another machine.
- The MCP server mounted in ``hx serve`` uses the server's own token.

.. code-block:: bash

   HYPOTHEX_HUB_URL=http://hub.example:7777 HYPOTHEX_HUB_TOKEN=... hx hosts status

SSH
---

- Hypothex uses your own ``ssh`` and ``scp`` and your ``~/.ssh/config``. It never
  stores SSH keys or passwords and never edits ``~/.ssh``.
- ``ssh`` runs with ``-o BatchMode=yes``: it never asks for a password. Tunnels add
  ``-o ExitOnForwardFailure=yes``, and every call uses
  ``ServerAliveInterval=15`` and ``ServerAliveCountMax=3``.
- Tunnels forward ``127.0.0.1`` on the hub to ``127.0.0.1`` on the host.
- Host names, SSH aliases, remote paths, and SLURM values are checked against strict
  patterns before they reach a shell. ``hx pull`` runs ``scp -s`` (SFTP mode), so the
  host's shell never reads a path.

Host identities
---------------

A host must report an environment identity different from the hub and from every
other configured host. The hub reserves the identity before reading the event
cursor or starting a mirror. The reservation uses the existing ``host_cursors``
row, including sequence zero, and survives disconnects, restarts, event-log
resets, and index rebuilds. Disabled hosts remain owners while they are configured.
Legacy run claims also preserve ownership when no cursor was saved.

Changing a host's connection settings does not release its current or previously
seen identities. To move an environment to another host name, remove the old
name with ``hx hosts rm OLD`` and add the new one. The old supervisor's pending
mirror writes finish before the identity is released. On accepting the new
name, the hub updates that environment's run-claim source labels before any new
data is mirrored. A different host cannot overwrite a claim while its old name
remains configured. Existing conflicting configured owners are refused rather
than choosing one arbitrarily.

No secrets in run files
-----------------------

- ``env/env_vars.json`` holds only an allow-list of variables
  (``CUDA_VISIBLE_DEVICES``, ``CUBLAS_WORKSPACE_CONFIG``, ``HF_HUB_OFFLINE``,
  ``OMP_NUM_THREADS``, ``PYTHONHASHSEED``, ``SLURM_JOB_ID``, ``SLURM_JOB_NODELIST``,
  ``TRANSFORMERS_OFFLINE``). API keys and tokens in your environment are never
  recorded.
- The recorded git ``origin`` URL has any user name, password, or token removed.
- Tokens are not in ``run.yaml``, ``environments.yaml``, or the API's answers.
- The run's command line *is* recorded, in ``run.yaml``. Do not pass secrets as
  command-line arguments; read them from environment variables or files in your code.
- Hypothex's own state in a run folder lives in ``.hx/``. The env server never serves
  a path in it (``404``), and the hub never copies one.

Report a problem
----------------

Please report a security problem privately to the maintainers, not in a public issue.
