Security model
==============

The Hypothex API starts arbitrary commands and reads run files. So every server is
reachable only from its own machine by default, every server requires a token,
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
- **Origin check**: a ``POST`` or WebSocket handshake whose ``Origin`` is not the
  server's own (the host and port the request was sent to, one of those hosts) gets
  ``403``. A page on another local server, such as Jupyter on ``localhost:8888``,
  is refused too. The Vite dev server forwards the browser's ``Host``, so its pages
  pass.
- **JSON posts**: a ``POST`` needs ``Content-Type: application/json`` or an
  ``X-Hypothex-Client`` header, else ``415``. A browser sends neither to another
  origin without a CORS preflight, which the server never grants.

These checks are not authentication: any program that is not a browser can send
``Host: localhost``.

Bearer token
------------

Every API, file and MCP request needs ``Authorization: Bearer <token>``. Only
``GET``/``HEAD`` of the exact descriptor ``/.well-known/hypothex/environment`` and
the installed UI's static resources/navigation are public. A
missing or wrong token gets ``401`` (``{"type": "AuthError"}``); a WebSocket is closed
with code ``1008``. Without the token the descriptor names only ``environment_id``,
``protocol_version`` and ``hx_version`` (``start.sh`` needs the id); the host name, OS,
GPUs and the rest are for the token holder. The public UI opens a Token gate;
ordinary page queries and the event stream start only after authentication.

**All servers**, including the local hub, have a token by default. Other local
users can reach ``127.0.0.1`` too.

- The token is ``HYPOTHEX_SERVE_TOKEN`` when set, else a new random one for each
  start.
- It is kept in ``<home>/serve/server.json`` on the host: mode 0600, in a 0700
  folder.
- The hub reads it over ``ssh`` during bootstrap and sends it through a private
  Unix-socket tunnel only after checking the endpoint's identity against the ID
  returned over SSH.
  It is never written to ``environments.yaml`` or to error messages.
- ``hx serve`` removes ``HYPOTHEX_SERVE_TOKEN`` from its environment at start, so the
  runs it starts never inherit it.
- ``--no-auth`` drops the token and is allowed only on a loopback bind. Use it
  only for explicit local test setups.

An explicit token must be 1–4096 ASCII characters: letters, digits,
``-._~+/``, with optional trailing ``=`` padding. Invalid values fail before a
listener or client is created, without echoing the value. A supplied token stays
the same across restarts; randomly generated tokens rotate on each actual start.
Reusing a live server preserves its token.

For the browser, run this locally using the same Hypothex home and paste its
output into the Token field:

.. code-block:: bash

   hx token

This explicit command prints the token from the private server record after
checking its home, host, environment identity and process birth. It makes no
network request and does not read ``HYPOTHEX_HUB_TOKEN``. Stale or unverifiable
records require a server restart. The browser keeps the credential in memory
and, when available, session storage. A ``401`` clears cached data and locks the
UI again; ``403`` and ``404`` do not.

Browser WebSockets use a fresh single-use ticket from
``POST /api/v1/auth/ws-ticket``. Tickets expire after 30 seconds and travel in
the offered ``hx-ticket.<ticket>`` subprotocol alongside ``hypothex.v1``; the
server selects only ``hypothex.v1``. Neither the bearer nor ticket appears in a
URL. At most 256 outstanding tickets are kept; issuance returns ``429`` when
full. Existing nonbrowser WebSocket clients can use the Authorization header.

Clients find the token like this:

- ``hx`` and ``hx mcp`` send ``HYPOTHEX_HUB_TOKEN`` when it is set.
- Else, for a hub on a loopback address, they read the token from that hub's
  ``<home>/serve/server.json`` (only when its port matches). A token is never read from
  that file for a hub on another machine.
- HTTP MCP forwards the caller's validated credential; it does not replace a
  missing or invalid credential with the server's root token.

Python hub and environment clients use explicit transports: they do not follow
redirects or inherit HTTP proxy and TLS configuration from environment variables.
Their HTTP diagnostics redact a configured bearer even when a peer reflects it
in response headers or status text.

.. code-block:: bash

   HYPOTHEX_HUB_URL=http://hub.example:7777 HYPOTHEX_HUB_TOKEN=... hx hosts status

SSH
---

- Hypothex uses your own ``ssh`` and ``scp`` and your ``~/.ssh/config``. It never
  stores SSH keys or passwords and never edits ``~/.ssh``.
- ``ssh`` runs with ``-o BatchMode=yes``: it never asks for a password. Tunnels add
  ``-o ExitOnForwardFailure=yes``, and every call uses
  ``ServerAliveInterval=15`` and ``ServerAliveCountMax=3``.
- Hub tunnels forward a Unix socket in a fresh 0700 local directory to
  ``127.0.0.1`` on the host. The socket is owner-only; there is no local TCP
  listener or fallback to one. Unsupported private forwarding fails closed.
- Bootstrap obtains the expected environment ID through SSH. The hub reads the
  tunneled public identity without a bearer, checks that ID and protocol, and
  only then constructs authenticated clients. Reconnects repeat this check.
  Private routes ignore HTTP proxy environment variables.
- Host names, SSH aliases, remote paths, and SLURM values are checked against strict
  patterns before they reach a shell. ``hx pull`` runs ``scp -s`` (SFTP mode), so the
  host's shell never reads a path.

The local private socket protects against another Unix user taking a public
local port. Same-user and root processes remain trusted because they can read
the private files. The remote end still uses loopback TCP; this does not protect
against replacement of the remote serving process or port by an attacker.

Project checkout paths
----------------------

``Context.local_repo`` is the shared gate for operations that read a registered
project's checkout or run code from it. A project copied from a host retains that
host's repo path for display, but the hub never reads it as a local checkout,
even when the same path exists here. Evaluation, datasets, view files, local
launches, reruns, and git pins use the gate. Read-only views can still use the
copied config's presets and inline definitions. Registering a checkout here
replaces the host copy without retaining its paths in local repo history.

Host identities
---------------

When ``environment.json`` is missing, identity recovery considers only runs with
this machine's hostname and no mirror claim. A host can report the same hostname
as the hub, so a matching hostname alone never makes a claimed mirror local.
Malformed claims and dangling claim symlinks still exclude their runs from recovery.

A host must report an environment identity different from the hub and from every
other configured host. The hub reserves the identity before reading the event
cursor or starting a mirror. The reservation uses the existing ``host_cursors``
row, including sequence zero, and survives disconnects, restarts, event-log
resets, and index rebuilds. Disabled hosts remain owners while they are configured.
Run claims with a host label also preserve ownership when no cursor was saved.

On upgrade, older run claims may contain only ``project`` and ``environment_id``.
The hub adds their ``host`` label only when existing cursor metadata identifies
exactly one original owner. It checks that ownership under the claim lock before
writing either a label or a new reservation. The first host to reconnect is never
assumed to be the owner.
All hostless claims are first labelled with that original owner before adding a
new alias cursor. A shutdown during normalization or alias transfer can therefore
resume without turning a known owner into an ambiguous one.

If those older claims have no saved cursor owner, or have several, the connection
is refused with a recovery message. Stop the hub and restore the original cursor
metadata from a trusted backup, or verify the source environment and add the
correct ``host`` label to its affected ``<store>/.claims/<run_id>.json`` files,
preserving their project and environment fields. Then reconnect. Removing claims
or accepting the first connecting host would discard the ownership evidence.

Changing a host's connection settings does not release its current or previously
seen identities. To move an environment to another host name, remove the old
name with ``hx hosts rm OLD`` and add the new one. The old supervisor's pending
mirror writes finish before the identity is released. On accepting the new
name, the hub updates that environment's run-claim source labels before any new
data is mirrored. A different host cannot overwrite a claim while its old name
remains configured. Existing conflicting configured owners are refused rather
than choosing one arbitrarily.
Forwarding prefers the current configured alias; historical cursor ownership is
still retained so edits to a removed host's mirrored runs cannot silently become
local-only changes.

No secrets in run files
-----------------------

- ``env/env_vars.json`` holds only an allow-list of variables
  (``CUDA_VISIBLE_DEVICES``, ``CUBLAS_WORKSPACE_CONFIG``, ``HF_HUB_OFFLINE``,
  ``OMP_NUM_THREADS``, ``PYTHONHASHSEED``, ``SLURM_JOB_ID``, ``SLURM_JOB_NODELIST``,
  ``TRANSFORMERS_OFFLINE``). API keys and tokens in your environment are never
  recorded.
- The recorded git ``origin`` URL has any user name, password, or token removed.
- Root bearer tokens are not in ``run.yaml``, ``environments.yaml``, or API
  answers. The authenticated ticket endpoint returns only its short-lived
  single-use WebSocket credential.
- The run's command line *is* recorded, in ``run.yaml``. Do not pass secrets as
  command-line arguments; read them from environment variables or files in your code.
- Hypothex's own state in a run folder lives in ``.hx/``. The env server never serves
  a path in it (``404``), and the hub never copies one.

Report a problem
----------------

Please report a security problem privately to the maintainers, not in a public issue.
