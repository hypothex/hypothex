Authentication foundations
==========================

The authentication store lives in ``<home>/auth/auth.db``, independently of the
rebuildable run index. The directory has mode 0700 and the database has mode 0600.
Only SHA-256 hashes of pairing and session secrets are stored in the database.
A reindex does not reset users, sessions, or revocations.

Scopes and execution
--------------------

Scopes are ordered ``read < launch < admin``. Launch scope permits ordinary run
mutations. Stopping, archiving, or cancelling a queued run additionally requires
ownership or admin scope. Legacy runs with no owner belong to the hub owner.

Starting a run on the serving machine requires admin scope: the process runs as
the server's Unix user and can read that user's files, including credentials.
Collaborators with launch scope use a configured host. Shared hosts should run
under a separate account from the hub owner; everyone launching on a host shares
that host's execution account. The host principal is trusted to forward identities
because the hub enforces the original caller's authorization before forwarding.

Pairing and sessions
--------------------

``AuthStore.ensure_owner`` bootstraps the first admin and is idempotent for an
existing enabled admin. It never promotes an existing collaborator or re-enables a
disabled account. Further admins are created by admin-issued pairing offers.
``mint_local`` accepts only an existing enabled admin. Disabling oneself or the
last enabled admin is refused.

An admin can invite a new user or pair another user's device. Other callers can
pair their own devices, up to their own scope and role. Offers expire after at
most 300 seconds, can be redeemed once, and are burned after five incorrect
secrets. A host session requires an admin offer. Pairing secrets are placed in the
URL fragment; browsers do not send fragments in the HTTP request target.
Automatically generated host session labels retain the ``hub:`` prefix and
shorten the hostname so the complete label fits the 64-character device limit.

Session tokens are returned once. Valid authentication extends the sliding
session lifetime at most once per minute. Revoked, expired, or disabled-user
sessions are rejected. Pairing redemption, failure counters, owner bootstrap,
and last-admin checks use SQLite transactions so concurrent callers cannot each
consume the same authorization.

For example, application code can create a read-only device offer::

    from hypothex.auth.store import AuthStore
    from hypothex.core.layout import Layout

    store = AuthStore(Layout(home))
    store.ensure_owner("owner")
    session, token = store.mint_local("owner")
    principal = store.authenticate(token)
    offer, secret = store.create_offer(
        issuer=principal, user="collaborator", scope="read"
    )

The returned token and secret are credentials. Do not include them in logs,
ordinary JSON output, event payloads, or run files.

WebSocket tickets
-----------------

Tickets carry a copied principal without a bearer secret. They are process-local,
expire after 30 monotonic seconds, and can be consumed only once. The default
capacity is 256 outstanding tickets; issuance returns ``None`` when full.
Revocation, session expiry, and disabled accounts are checked again on redemption.
``session_active`` supports subsequent socket checks without sliding the session.
The existing root ticket store retains its boolean ``issue``/``consume`` behavior.

CLI login storage
-----------------

CLI hub logins are stored by normalized hub URL in
``<home>/auth/hub-tokens.json`` with mode 0600 inside the private auth directory.
Updates lock the whole file operation so simultaneous logins and logouts preserve
other hubs. Missing, malformed, insecure, or symlinked token files are unavailable.

``HubLogin.token`` is a ``pydantic.SecretStr``. Its representation and ordinary
JSON serialization mask the credential. ``save_hub_login`` explicitly unwraps it
at the private file boundary. HTTP consumers must similarly call
``login.token.get_secret_value()`` only when setting the Authorization header::

    login = hub_login(layout, hub_url)
    if login is not None:
        headers = {"Authorization": f"Bearer {login.token.get_secret_value()}"}

These modules provide the authentication foundation. HTTP routes, CLI commands,
and their startup integration are implemented separately.
