Hub configuration
=================

The hub reads ``<home>/config.yaml``. A missing file uses local defaults:
scoped collaboration auth is off, notifications and the weekly digest are
inactive, and the disposable index is SQLite. This file is separate from a
project's ``hypothex.yaml`` and a run's captured configuration.

Name secrets by their environment variables, never by their values:

.. code-block:: yaml

   server:
     auth: off
     session_days: 90
   notify:
     slack:
       webhook_env: LAB_SLACK_WEBHOOK
     projects:
       toy:
         events: [finished, failed, lost]
         channels: [slack]
         min_seconds: 300
         fold_sweeps: true

The optional ``<home>/secrets.env`` accepts ``NAME=value`` lines, comments,
optional ``export`` prefixes, and matching single or double quotes. It performs
no shell expansion. The current process environment takes precedence; an empty
value falls back to the file. The file must belong to the current user and
have no group or other permission bits (``chmod 600 secrets.env``).

Settings reject unknown fields, invalid environment variable names, cyclic or
overly nested YAML, literal Slack/SMTP secrets, and passwords in Postgres URLs.
Validation errors omit input values. For Postgres, use a password-free
``server.index_url`` and ``server.index_password_env``. SMTP settings support
``starttls``, ``ssl`` and ``none``; a username with ``none`` is allowed only on
loopback. Digest timezones use IANA names such as ``Europe/London``.

Python usage
------------

.. code-block:: python

   from pathlib import Path
   from hypothex.core.layout import Layout
   from hypothex.core.settings import (
       NotifySettings, ProjectRule, Settings, SlackSettings,
       load_settings, resolve_secret, save_settings,
   )

   layout = Layout(Path("/tmp/example-hypothex"))
   settings = Settings(notify=NotifySettings(
       slack=SlackSettings(webhook_env="LAB_SLACK_WEBHOOK"),
       projects={"toy": ProjectRule(channels=["slack"])},
   ))
   save_settings(layout, settings)
   assert load_settings(layout) == settings
   secret = resolve_secret(layout, "LAB_SLACK_WEBHOOK")  # SecretStr or None

Saving settings is atomic, omits defaults, sets the file to mode 0600, and
sets the home directory to 0700. Keep that home private to its serving user.
Run command environments omit configured notification and index secret
variables plus the default Hypothex webhook, password and bearer variables.

Ownership and index upgrade
---------------------------

Run records, launch requests and sweep definitions accept ``owner`` as an
optional user name. Legacy records default to ``None``. Rerun and reinfer
children take the caller's supplied owner; sweep extensions preserve the
original sweep owner. ``Index.list_runs(owner="alice")`` and
``Index.count_runs(owner="alice")`` combine ownership with existing filters,
literal name search and pagination. Opening a home with SQLite schema 3 or 4
rebuilds its disposable index as schema 5 from the original run files.
