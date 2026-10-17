Notifications and weekly digests
================================

The hub can send Slack and SMTP notices when opted-in project runs finish,
fail, or become lost. Hosts do not run a notifier; their terminal mirror events
are handled by the hub. Configuration is read again on each notifier tick.

Configuration
-------------

Configure channels and opt projects in through the hub's ``config.yaml``.
Only environment variable names belong in this file; supply their values in
the hub's environment or a private, mode-0600 ``secrets.env`` file.

After creating ``secrets.env``, make it readable and writable only by its owner:

.. code-block:: bash

   chmod 600 ~/.hypothex/secrets.env

The file must belong to the account running the hub. Hypothex refuses a file
owned by another user, readable or writable by others, or containing malformed
entries. Correct its ownership and permissions before retrying; an unsafe
secrets file produces the delivery error class ``secrets_file``.

.. code-block:: yaml

   notify:
     slack:
       webhook_env: HYPOTHEX_SLACK_WEBHOOK
     email:
       host: smtp.example.org
       port: 587
       security: starttls
       username: researcher
       password_env: HYPOTHEX_SMTP_PASSWORD
       sender: hypothex@example.org
       to: [researcher@example.org]
     projects:
       chemistry:
         channels: [slack, email]
         events: [finished, failed, lost]
         min_seconds: 60
         fold_sweeps: true
     max_age_hours: 24
   digest:
     enabled: true
     weekday: mon
     hour: 9
     timezone: Europe/London
     projects: [chemistry]
     channels: [slack, email]
     save_to_notebook: true
     top_notes: 5

A project without a rule receives no terminal-run notices unless ``notify.default``
is configured. ``min_seconds`` filters successful short runs; failures still
notify. A channel without configuration is omitted at enqueue time. Slack
requires HTTPS except on loopback; SMTP supports verified STARTTLS or implicit
TLS, with plaintext permitted only on loopback. The SMTP greeting identifies
this client using its connected socket's numeric local address (IPv4 or IPv6),
avoiding an unbounded local machine-name DNS lookup for every message. Remote
server resolution and TLS hostname verification still use the configured host.

Use ``hx notify status`` to inspect configuration and recent delivery outcomes,
and ``hx notify test slack`` for an immediate test. Status reports
whether secret variables are set and never returns their values.

Delivery and sweep folding
--------------------------

The first notifier start checkpoints the current event sequence, avoiding an
old-run backlog flood. Each later qualifying run produces a deterministic
notice ID and one durable outbox entry per configured channel.

Sweep folding recognizes this hub's member tag. Another hub's sweep with the
same ID remains a separate run notice. A sweep waits until every observed
member is terminal and its durable issuance episode has settled. Legacy
sweeps also wait while a launch lock is held and members are still missing.
Deferred sweep triggers survive restart and are reconsidered without needing
another event. A failed partial launch can therefore report its final partial
membership. The configured event filter applies to the sweep's outcomes.

Delivery is at least once. Slack 429 and 5xx responses, timeouts, and temporary
SMTP failures retry after 30 seconds, 2 minutes, and 10 minutes. A valid
``Retry-After`` may lengthen those waits. The fourth failed attempt is final.
Permanent failures, including SMTP authentication failure, finish immediately.
Missing secrets and removed channels are recorded as skipped.

An SMTP message is successful only when every recipient is accepted. Partial
recipient refusals are recorded as failures too. If any refused recipient has
a temporary 4xx response, the whole email batch follows the bounded retry
schedule, even when another recipient has a permanent 5xx refusal. Once only
permanent refusals remain, the entry fails immediately. Recipients accepted
on an earlier attempt may receive duplicate copies on a batch retry; delivery
is at least once and the outbox does not track individual recipients. Stored
diagnostics contain only an SMTP error class, never recipient addresses or
server reply text.

A crash after sending but before recording success can cause one resend after
60 seconds. Once the final record exists, an outbox entry left by a crash is
removed without resending. Concurrent notifier instances serialize outbox
writes and delivery. The journal repairs an interrupted last line before the
next append and flushes final records before removing outbox entries.

State lives under ``<home>/notify``: ``cursor.json``, ``pending-sweeps.json``,
``outbox/``, ``sent.jsonl``, and ``digest.json``. State files are private.
Errors stored in history and events are short classes such as ``http_429`` or
``smtp_535``. Configured secret values and webhook paths are redacted before
notices are persisted. History and note files are streamed; notification
entries are limited to 1 MiB, and recent history retains only the requested
number of message payloads in memory.

Weekly summaries
----------------

A digest includes runs created and ended in its inclusive time window,
counts by creator, recorded cost, leaderboard changes, the newest stamped
run/notebook notes, and new sweeps. Notes are cut to 200 characters; prior
digest entries are excluded. The same top notes appear in Slack, email, and
the notebook copy.

Scheduled windows end at that week's configured send time in the configured
IANA timezone, or the machine's local timezone when omitted. A hub restarted
later in the same week catches up once; earlier missed weeks are skipped.
Stable windows give retried digests the same notice ID and notebook stamp.
An oversized notebook day skips only the notebook copy, while queued channel
notices and the weekly checkpoint still proceed. A digest error cannot stop
other pending notices from being delivered.

Cost uncertainty survives every representation. Only explicitly complete
pricing displays ``$2.25``. Partial or legacy pricing displays
``Cost unknown · $2.25 recorded``, including a zero recorded subtotal.
Missing run cost uses recorded API usage and unpriced GPU time; the digest
aggregates every ended run. An empty digest window is an explicitly complete
zero. No legacy record is repriced by generating a notice.

Python usage
------------

Build a summary without delivering it:

.. code-block:: python

   from datetime import UTC, datetime, timedelta
   from hypothex.core.digest import build_digest, render_digest_markdown

   end = datetime.now(UTC)
   digest = build_digest(ctx, "chemistry", since=end - timedelta(days=7), until=end)
   markdown = render_digest_markdown(digest)

``send_digest(ctx, settings, project, now=end)`` enqueues configured channels
and saves the notebook copy. ``Notifier.deliver()`` performs due deliveries;
``Notifier.tick()`` scans events, schedules digests, and delivers in that order.
Tests use loopback Slack/SMTP servers and locally trusted fake TLS certificates.
