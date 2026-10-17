"""Users, pairing offers, sessions, and principals (state in ``<home>/auth/auth.db``)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from hypothex.api.tickets import TICKET_CAPACITY, TicketStore
from hypothex.auth.scopes import Scope, covers
from hypothex.core.errors import ConfigError, HypothexError, StoreError
from hypothex.core.ids import utcnow
from hypothex.core.layout import Layout

USER_NAME = r"^[a-z][a-z0-9_-]{0,31}$"
Client = Literal["browser", "cli", "agent", "host", "local"]
PAIRING_TTL_SECONDS = 300
PAIRING_MAX_FAILURES = 5
TICKET_TTL_SECONDS = 30
PAIRING_INVALID = "pairing link invalid or expired; run hx pair again"


class AuthError(HypothexError):
    """No valid session (HTTP 401)."""


class ScopeError(HypothexError):
    """The principal's scope or ownership does not allow the action (HTTP 403)."""


class PairingError(HypothexError):
    """A pairing link is unknown, expired, used, or has a wrong secret (HTTP 400)."""


class User(BaseModel):
    """A person (or the hub owner) who may hold sessions."""

    name: str
    role: Scope
    created_at: datetime
    created_by: str
    disabled_at: datetime | None = None


class Session(BaseModel):
    """A revocable session of one device; its secret is stored as a sha256."""

    id: str
    user: str
    scope: Scope
    client: Client
    device: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class PairingOffer(BaseModel):
    """A one-time pairing link (``hx pair``)."""

    id: str
    user: str
    new_user: bool
    scope: Scope
    issued_by: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    failures: int = 0


class Principal(BaseModel):
    """Who is calling: a user's session, the local owner, or a hub forwarding."""

    user: str
    scope: Scope
    session_id: str | None
    client: Client
    agent: str | None = None

    def identity(self) -> str:
        """
        Return the ``created_by`` value for runs this principal starts.

        Returns
        -------
        str
            ``agent:<agent>@<user>`` when an agent acts for the user, else
            ``human:<user>``.

        Examples
        --------
        >>> Principal(user="al", scope="read", session_id=None, client="cli").identity()
        'human:al'
        """
        if self.agent:
            return f"agent:{self.agent}@{self.user}"
        return f"human:{self.user}"


LOCAL_OWNER = Principal(user="local", scope="admin", session_id=None, client="local")
"""Every request when auth is off (phase 1-2 behaviour)."""
HOST_PRINCIPAL = Principal(user="hub", scope="admin", session_id=None, client="host")
"""A hub forwarding to a host (``TokenGuard`` token or ``host_token``)."""

AUTH_DIR = "auth"
AUTH_DB = "auth.db"
LAST_SEEN_EVERY = timedelta(seconds=60)
TOKEN_PREFIX = "hxs_"
_TOKEN = re.compile(r"^hxs_(s_[0-9a-f]{12})_([A-Za-z0-9_-]{43})$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  name TEXT PRIMARY KEY, role TEXT NOT NULL, created_at TEXT NOT NULL,
  created_by TEXT NOT NULL, disabled_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user TEXT NOT NULL, scope TEXT NOT NULL, client TEXT NOT NULL,
  device TEXT NOT NULL, secret_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS offers (
  id TEXT PRIMARY KEY, user TEXT NOT NULL, new_user INTEGER NOT NULL, scope TEXT NOT NULL,
  issued_by TEXT NOT NULL, secret_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, used_at TEXT, failures INTEGER NOT NULL DEFAULT 0
);
"""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _same(secret: str, stored: str) -> bool:
    return hmac.compare_digest(_hash(secret), stored)


def _at(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def parse_token(token: str) -> tuple[str, str] | None:
    """
    Split a session token into its session id and secret.

    Parameters
    ----------
    token : str
        ``hxs_<session id>_<secret>``.

    Returns
    -------
    tuple of (str, str) or None
        ``(session_id, secret)``; None when the text is not a token.

    Examples
    --------
    >>> parse_token("hxs_s_0123456789ab_" + "a" * 43)[0]
    's_0123456789ab'
    >>> parse_token("nope") is None
    True
    """
    match = _TOKEN.fullmatch(token)
    return (match.group(1), match.group(2)) if match else None


class AuthStore:
    """
    Users, pairing offers, sessions, and WebSocket tickets of one hub.

    State lives in ``<home>/auth/auth.db`` (SQLite; folder 0700, file 0600),
    never in the index: ``hx reindex`` does not touch it. Secrets are stored
    as sha256 and compared in constant time. Tickets live in memory only.

    Parameters
    ----------
    layout : Layout
        The hub's home.
    now : callable, optional
        Clock (tests pass a fake one).
    session_days : int
        Session lifetime; it slides with use.
    ticket_clock : callable, optional
        Monotonic clock used only for ticket expiry.
    ticket_capacity : int, optional
        Maximum outstanding tickets, at most 256.
    """

    def __init__(
        self,
        layout: Layout,
        *,
        now: Callable[[], datetime] = utcnow,
        session_days: int = 90,
        ticket_clock: Callable[[], float] = time.monotonic,
        ticket_capacity: int = TICKET_CAPACITY,
    ) -> None:
        if isinstance(session_days, bool) or not isinstance(session_days, int) or session_days < 1:
            raise ConfigError("session_days must be a positive integer")
        if (
            isinstance(ticket_capacity, bool)
            or not isinstance(ticket_capacity, int)
            or not 1 <= ticket_capacity <= TICKET_CAPACITY
        ):
            raise ConfigError("ticket capacity must be 1..256")
        self.now = now
        self.session_days = session_days
        self.tickets = TicketStore(clock=ticket_clock, capacity=ticket_capacity)
        folder = layout.home / AUTH_DIR
        if folder.is_symlink():
            raise ConfigError("auth directory must not be a symlink")
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        self.path: Path = folder / AUTH_DB
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise ConfigError("auth database must be an owned regular file")
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        except OSError:
            raise ConfigError("cannot open private auth database") from None
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if conn.in_transaction:
                conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    # users ---------------------------------------------------------------------------
    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            name=row["name"],
            role=row["role"],
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
            disabled_at=_at(row["disabled_at"]),
        )

    def ensure_owner(self, name: str) -> User:
        """
        Create the first admin, or return an existing enabled admin.

        Parameters
        ----------
        name : str
            User name (``USER_NAME``).

        Returns
        -------
        User
            The owner.

        Raises
        ------
        ConfigError
            The name does not match ``USER_NAME``.
        ScopeError
            Bootstrap already occurred or the named user is not an active admin.
        """
        if not re.fullmatch(USER_NAME, name):
            raise ConfigError(f"user name {name!r} must match {USER_NAME}")
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            if row is not None:
                if row["role"] != "admin" or row["disabled_at"] is not None:
                    raise ScopeError("owner must be an active admin")
                return self._user(row)
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
                raise ScopeError("owner already initialized; pair another admin")
            conn.execute(
                "INSERT INTO users(name, role, created_at, created_by) VALUES (?,?,?,?)",
                (name, "admin", self.now().isoformat(), "hx serve"),
            )
            row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            return self._user(row)

    def users(self) -> list[User]:
        """
        List every user, by name.

        Returns
        -------
        list of User
        """
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [self._user(r) for r in rows]

    def get_user(self, name: str) -> User | None:
        """
        Return one user, or None.

        Parameters
        ----------
        name : str

        Returns
        -------
        User or None
        """
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        return None if row is None else self._user(row)

    def disable_user(self, name: str, *, by: Principal) -> User:
        """
        Disable a user and revoke every session they hold (admin only).

        Parameters
        ----------
        name : str
            User to disable.
        by : Principal
            The caller; must be ``admin`` and not ``name``.

        Returns
        -------
        User
            The disabled user.

        Raises
        ------
        ScopeError
            The caller is not admin, or names themselves.
        StoreError
            No such user (404).
        """
        if by.scope != "admin":
            raise ScopeError("disabling users needs admin")
        if by.user == name:
            raise ScopeError("you cannot disable yourself")
        now = self.now().isoformat()
        with self._conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            if target is None:
                raise StoreError(f"no user {name!r}")
            if target["role"] == "admin" and target["disabled_at"] is None:
                count = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL"
                ).fetchone()[0]
                if count <= 1:
                    raise ScopeError("cannot disable the last active admin")
            done = conn.execute(
                "UPDATE users SET disabled_at = COALESCE(disabled_at, ?) WHERE name = ?",
                (now, name),
            ).rowcount
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user = ? AND revoked_at IS NULL",
                (now, name),
            )
        if not done:
            raise StoreError(f"no user {name!r}")
        user = self.get_user(name)
        assert user is not None
        return user

    # pairing -------------------------------------------------------------------------
    def create_offer(
        self,
        *,
        issuer: Principal,
        user: str,
        scope: Scope,
        ttl_seconds: int = PAIRING_TTL_SECONDS,
    ) -> tuple[PairingOffer, str]:
        """
        Issue a one-time pairing offer; never wider than the issuer or the user's role.

        Parameters
        ----------
        issuer : Principal
            Who asks for the link.
        user : str
            The user the new session belongs to; a name that does not exist yet
            makes a new user with role ``scope`` (admin only).
        scope : Scope
            Scope of the session the link creates.
        ttl_seconds : int
            Lifetime, 1 to 300 seconds.

        Returns
        -------
        tuple of (PairingOffer, str)
            The offer and its secret (shown once, in the link's fragment).

        Raises
        ------
        PairingError
            ``ttl_seconds`` outside 1..300.
        ConfigError
            A user name that does not match ``USER_NAME``.
        ScopeError
            ``scope`` is wider than the issuer's scope or the user's role; a new
            user or another user's device without ``admin``; a disabled user.
        """
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= PAIRING_TTL_SECONDS
        ):
            raise PairingError(f"ttl must be 1..{PAIRING_TTL_SECONDS} seconds")
        if not re.fullmatch(USER_NAME, user):
            raise ConfigError(f"user name {user!r} must match {USER_NAME}")
        if not covers(issuer.scope, scope):
            raise ScopeError(f"cannot pair with scope {scope}: you hold {issuer.scope}")
        target = self.get_user(user)
        if target is None and issuer.scope != "admin":
            raise ScopeError("adding a user needs admin")
        if target is not None:
            if target.name != issuer.user and issuer.scope != "admin":
                raise ScopeError("pairing another user's device needs admin")
            if target.disabled_at is not None:
                raise ScopeError(f"user {user} is disabled")
            if not covers(target.role, scope):
                raise ScopeError(f"user {user} has role {target.role}; cannot pair {scope}")
        now = self.now()
        offer = PairingOffer(
            id=f"p_{secrets.token_hex(6)}",
            user=user,
            new_user=target is None,
            scope=scope,
            issued_by=issuer.user,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        secret = secrets.token_urlsafe(32)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO offers(id, user, new_user, scope, issued_by, secret_hash, "
                "created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    offer.id, offer.user, int(offer.new_user), offer.scope, offer.issued_by,
                    _hash(secret), now.isoformat(), offer.expires_at.isoformat(),
                ),
            )  # fmt: skip
        return offer, secret

    def redeem(
        self, offer_id: str, secret: str, *, client: Client, device: str
    ) -> tuple[Session, str]:
        """
        Exchange a pairing offer for a session (once).

        Parameters
        ----------
        offer_id : str
            ``p_<12 hex>`` from the link.
        secret : str
            The link's secret.
        client : Client
            ``browser``, ``cli``, ``agent``, or ``host``. A ``host`` session is
            trusted to forward ``created_by``/``owner`` for other users, so only
            an ``admin`` offer (issued by an admin) may be redeemed as ``host``.
        device : str
            A label shown in the sessions list (cut to 64 characters).

        Returns
        -------
        tuple of (Session, str)
            The session and its token ``hxs_<session id>_<secret>`` (shown once).

        Raises
        ------
        PairingError
            Unknown, expired, used, burned, or wrong secret, or ``client="host"``
            on an offer below ``admin``: always the same message.
        """
        if client not in ("browser", "cli", "agent", "host"):
            raise PairingError(PAIRING_INVALID)
        now = self.now()
        with self._conn() as conn:
            try:
                session, token = self._redeem_in(conn, offer_id, secret, client, device, now)
            except PairingError:
                conn.execute("COMMIT")  # keeps a failure count written by _redeem_in
                raise
        return session, token

    def _redeem_in(
        self,
        conn: sqlite3.Connection,
        offer_id: str,
        secret: str,
        client: Client,
        device: str,
        now: datetime,
    ) -> tuple[Session, str]:
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if (
            row is None
            or row["used_at"] is not None
            or row["failures"] >= PAIRING_MAX_FAILURES
            or datetime.fromisoformat(row["expires_at"]) <= now
        ):
            raise PairingError(PAIRING_INVALID)
        if not _same(secret, row["secret_hash"]):
            conn.execute("UPDATE offers SET failures = failures + 1 WHERE id = ?", (offer_id,))
            raise PairingError(PAIRING_INVALID)
        if client == "host" and row["scope"] != "admin":
            raise PairingError(PAIRING_INVALID)  # only an admin may mint a forwarding credential
        user = conn.execute("SELECT * FROM users WHERE name = ?", (row["user"],)).fetchone()
        if row["new_user"]:
            if user is not None:
                raise PairingError(PAIRING_INVALID)
            conn.execute(
                "INSERT INTO users(name, role, created_at, created_by) VALUES (?,?,?,?)",
                (row["user"], row["scope"], now.isoformat(), row["issued_by"]),
            )
        elif (
            user is None
            or user["disabled_at"] is not None
            or not covers(user["role"], row["scope"])
        ):
            raise PairingError(PAIRING_INVALID)
        conn.execute("UPDATE offers SET used_at = ? WHERE id = ?", (now.isoformat(), offer_id))
        return self._new_session(conn, row["user"], row["scope"], client, device, now)

    def _new_session(
        self,
        conn: sqlite3.Connection,
        user: str,
        scope: str,
        client: str,
        device: str,
        now: datetime,
    ) -> tuple[Session, str]:
        session_id = f"s_{secrets.token_hex(6)}"
        secret = secrets.token_urlsafe(32)
        expires = now + timedelta(days=self.session_days)
        conn.execute(
            "INSERT INTO sessions(id, user, scope, client, device, secret_hash, created_at, "
            "last_seen_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                session_id, user, scope, client, device[:64], _hash(secret), now.isoformat(),
                now.isoformat(), expires.isoformat(),
            ),
        )  # fmt: skip
        session = Session.model_validate(
            {
                "id": session_id,
                "user": user,
                "scope": scope,
                "client": client,
                "device": device[:64],
                "created_at": now,
                "last_seen_at": now,
                "expires_at": expires,
            }
        )
        return session, f"{TOKEN_PREFIX}{session_id}_{secret}"

    # sessions ------------------------------------------------------------------------
    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        data: dict[str, Any] = {k: row[k] for k in row.keys() if k != "secret_hash"}  # noqa: SIM118
        return Session.model_validate(data)

    def authenticate(self, token: str) -> Principal | None:
        """
        Turn a session token into a principal.

        Parameters
        ----------
        token : str
            ``hxs_...`` token (cookie or bearer).

        Returns
        -------
        Principal or None
            None for a malformed, unknown, revoked, or expired token, a wrong
            secret, or a disabled user. A valid use slides the session at most
            once per 60 s.
        """
        parts = parse_token(token)
        if parts is None:
            return None
        session_id, secret = parts
        now = self.now()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None or not _same(secret, row["secret_hash"]):
                return None
            if row["revoked_at"] is not None or datetime.fromisoformat(row["expires_at"]) <= now:
                return None
            user = conn.execute(
                "SELECT disabled_at FROM users WHERE name = ?", (row["user"],)
            ).fetchone()
            if user is None or user["disabled_at"] is not None:
                return None
            if now - datetime.fromisoformat(row["last_seen_at"]) >= LAST_SEEN_EVERY:
                conn.execute(
                    "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                    (
                        now.isoformat(),
                        (now + timedelta(days=self.session_days)).isoformat(),
                        session_id,
                    ),
                )
        return Principal(
            user=row["user"], scope=row["scope"], session_id=session_id, client=row["client"]
        )

    def sessions(self, user: str | None = None) -> list[Session]:
        """
        List active sessions (not revoked, not expired), newest first.

        Parameters
        ----------
        user : str, optional
            Only this user's sessions.

        Returns
        -------
        list of Session
        """
        sql = "SELECT * FROM sessions WHERE revoked_at IS NULL AND expires_at > ?"
        args: list[str] = [self.now().isoformat()]
        if user is not None:
            sql += " AND user = ?"
            args.append(user)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, id", args).fetchall()
        return [self._session(r) for r in rows]

    def revoke(self, session_id: str, *, by: Principal) -> Session:
        """
        Revoke a session: the caller's own, or anyone's for an admin.

        Parameters
        ----------
        session_id : str
        by : Principal

        Returns
        -------
        Session
            The revoked session.

        Raises
        ------
        StoreError
            No such session (404).
        ScopeError
            Another user's session without ``admin``.
        """
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise StoreError(f"no session {session_id!r}")
            if row["user"] != by.user and by.scope != "admin":
                raise ScopeError("revoking another user's session needs admin")
            conn.execute(
                "UPDATE sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (self.now().isoformat(), session_id),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session(row)

    def mint_local(self, user: str) -> tuple[Session, str]:
        """
        Create the admin session ``hx serve`` writes into its own ``server.json``.

        Parameters
        ----------
        user : str
            An existing admin (normally the owner).

        Returns
        -------
        tuple of (Session, str)
            Client ``local``, scope ``admin``; ``hx serve`` revokes it at stop.

        Raises
        ------
        ScopeError
            The user is missing, disabled, or not an admin.
        """
        with self._conn() as conn:
            target = conn.execute("SELECT * FROM users WHERE name = ?", (user,)).fetchone()
            if target is None or target["disabled_at"] is not None or target["role"] != "admin":
                raise ScopeError(f"{user} is not an active admin")
            return self._new_session(conn, user, "admin", "local", "hx serve", self.now())

    def issue_ticket(self, principal: Principal) -> str | None:
        """Issue a bounded one-use ticket for a currently valid principal.

        Parameters
        ----------
        principal : Principal
            Guard-selected caller; the payload holds no bearer secret.

        Returns
        -------
        str or None
            Ticket, or None at capacity (the HTTP route returns 429).
        """
        if principal.session_id and not self.session_active(principal.session_id):
            raise AuthError("session is no longer active")
        return self.tickets.issue(principal.model_copy(deep=True))

    def redeem_ticket(self, ticket: str) -> Principal | None:
        """Consume a ticket once and recheck session revocation and expiry.

        Parameters
        ----------
        ticket : str
            Secret from the ticket subprotocol.

        Returns
        -------
        Principal or None
            Selected caller, or None for an invalid ticket/session.
        """
        principal = self.tickets.redeem(ticket)
        if not isinstance(principal, Principal):
            return None
        if principal.session_id and not self.session_active(principal.session_id):
            return None
        return principal

    def session_active(self, session_id: str) -> bool:
        """
        Tell whether a session is still usable (checked by open WebSockets).

        Parameters
        ----------
        session_id : str

        Returns
        -------
        bool
            False when it is unknown, revoked, expired, or its user is disabled.
            Unlike ``authenticate`` it never slides the session.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT s.revoked_at, s.expires_at, u.disabled_at FROM sessions s "
                'JOIN users u ON u.name = s."user" WHERE s.id = ?',
                (session_id,),
            ).fetchone()
        return (
            row is not None
            and row["revoked_at"] is None
            and row["disabled_at"] is None
            and datetime.fromisoformat(row["expires_at"]) > self.now()
        )
