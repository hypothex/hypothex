import os
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr

from hypothex.core.envcapture import ENV_ALLOWLIST
from hypothex.core.errors import ConfigError
from hypothex.core.layout import Layout
from hypothex.core.settings import (
    EmailSettings,
    NotifySettings,
    ProjectRule,
    SecretsFileError,
    Settings,
    SlackSettings,
    check_secrets_file,
    load_settings,
    redact_url,
    resolve_secret,
    save_settings,
    scrub_env,
    secret_env_names,
    secrets_path,
    settings_path,
    write_private,
)

FULL = """\
server:
  auth: off
  public_url: null
  session_days: 90
  index_url: null
  index_password_env: HYPOTHEX_INDEX_PASSWORD
notify:
  slack: {webhook_env: HYPOTHEX_SLACK_WEBHOOK}
  email:
    host: smtp.lab.org
    port: 587
    security: starttls
    username: sv
    password_env: HYPOTHEX_SMTP_PASSWORD
    sender: hx@lab.org
    to: [sv@lab.org]
    timeout: 20
  projects:
    deepretro:
      events: [finished, failed, lost]
      channels: [slack, email]
      min_seconds: 300
      fold_sweeps: true
  default: null
  max_age_hours: 24
digest:
  enabled: true
  weekday: mon
  hour: 9
  timezone: Europe/London
  channels: [slack]
  projects: all
  save_to_notebook: true
  top_notes: 5
storage: {older_than_days: 30, kinds: [checkpoint], plan_ttl_minutes: 60}
"""
SECRET = "T0AAAA/B0BBBB/SECRETXYZ"


def write(home: Path, text: str) -> Layout:
    layout = Layout(home)
    home.mkdir(parents=True, exist_ok=True)
    settings_path(layout).write_text(text)
    return layout


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    settings = load_settings(Layout(tmp_path))
    assert settings == Settings()
    assert settings.server.auth == "off" and settings.notify.default is None
    assert settings.digest.enabled is False and settings.storage.kinds == ["checkpoint"]


def test_contract_example_loads(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, FULL))
    rule = settings.notify.projects["deepretro"]
    assert rule.channels == ["slack", "email"] and rule.min_seconds == 300
    assert settings.notify.email is not None and settings.notify.email.to == ["sv@lab.org"]
    assert settings.digest.timezone == "Europe/London" and settings.digest.projects == "all"
    assert settings.server.index_password_env == "HYPOTHEX_INDEX_PASSWORD"


@pytest.mark.parametrize("key", ["webhook", "webhook_url", "url", "token", "secret"])
def test_literal_slack_secret_is_refused_without_echo(tmp_path: Path, key: str) -> None:
    text = f"notify:\n  slack:\n    {key}: https://hooks.slack.com/services/{SECRET}\n"
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    message = str(info.value)
    assert f"notify.slack.{key}" in message and "line 3" in message
    assert "use webhook_env: NAME" in message
    assert "SECRETXYZ" not in message and "hooks.slack.com" not in message


@pytest.mark.parametrize("key", ["password", "token", "secret"])
def test_literal_smtp_secret_is_refused_without_echo(tmp_path: Path, key: str) -> None:
    text = (
        "notify:\n  email:\n    host: smtp.lab.org\n    sender: a@b.c\n    to: [a@b.c]\n"
        f"    {key}: hunter2-SECRETXYZ\n"
    )
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    assert "use password_env: NAME" in str(info.value) and "line 6" in str(info.value)
    assert "SECRETXYZ" not in str(info.value)


def test_index_url_with_a_password_is_refused_redacted(tmp_path: Path) -> None:
    text = "server:\n  index_url: postgresql+psycopg://hx:pw-SECRETXYZ@db.lab:5432/hx\n"
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    assert "postgresql+psycopg://hx:***@db.lab:5432/hx" in str(info.value)
    assert "SECRETXYZ" not in str(info.value)


def test_redact_url() -> None:
    assert redact_url("postgresql://u:p@h:5/d") == "postgresql://u:***@h:5/d"
    assert redact_url("postgresql://u@h/d") == "postgresql://u@h/d"
    assert redact_url("postgresql://u@h/d?Password=p&sslmode=require") == (
        "postgresql://u@h/d?Password=***&sslmode=require"
    )


def test_index_url_with_a_password_parameter_is_refused_redacted(tmp_path: Path) -> None:
    # libpq (and so SQLAlchemy) takes ?password= as the connection password
    for key in ("password", "PASSWORD", "sslpassword", "pass%77ord"):
        text = f"server:\n  index_url: postgresql+psycopg://hx@db.lab/hx?{key}=pw-SECRETXYZ\n"
        with pytest.raises(ConfigError) as info:
            load_settings(write(tmp_path, text))
        assert "holds a password" in str(info.value) and "SECRETXYZ" not in str(info.value)


def test_env_names_are_checked(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="notify.slack.webhook_env"):
        load_settings(write(tmp_path, "notify:\n  slack: {webhook_env: lower-case}\n"))


def test_clear_text_smtp_login_is_refused_off_loopback() -> None:
    with pytest.raises(ValueError, match="clear text"):
        EmailSettings(
            host="smtp.lab.org", security="none", username="sv", sender="a@b.c", to=["a@b.c"]
        )
    local = EmailSettings(
        host="127.0.0.1", security="none", username="sv", sender="a@b.c", to=["a@b.c"]
    )
    assert local.security == "none"


def test_unknown_timezone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="digest.timezone"):
        load_settings(write(tmp_path, "digest: {timezone: Mars/Olympus}\n"))


def test_unknown_key_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="notifications"):
        load_settings(write(tmp_path, "notifications: {}\n"))


def test_validation_errors_never_echo_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, "server:\n  session_days: SECRETXYZ\n"))
    assert "server.session_days" in str(info.value) and "SECRETXYZ" not in str(info.value)


def test_too_deep_yaml_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="line 1"):
        load_settings(write(tmp_path, "a: " + "[" * 70 + "]" * 70 + "\n"))


def test_save_round_trips_with_mode_0600(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "home")
    settings = Settings(
        notify=NotifySettings(
            slack=SlackSettings(), projects={"toy": ProjectRule(channels=["slack"])}
        )
    )
    save_settings(layout, settings)
    path = settings_path(layout)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_settings(layout) == settings
    assert "storage" not in path.read_text()  # defaults are left out
    assert os.access(path, os.R_OK)


def test_write_private_ignores_a_stale_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "home" / "server.json"
    path.parent.mkdir()
    stale = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    stale.write_text("old")
    stale.chmod(0o644)  # os.replace would carry this mode onto the token file
    write_private(path, "{}")
    assert path.read_text() == "{}" and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not stale.exists()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def secrets_file(home: Path, text: str, mode: int = 0o600) -> Layout:
    layout = Layout(home)
    home.mkdir(parents=True, exist_ok=True)
    path = secrets_path(layout)
    path.write_text(text)
    path.chmod(mode)
    return layout


def test_environment_wins_over_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = secrets_file(tmp_path, "LAB_HOOK=https://from-file\n")
    monkeypatch.setenv("LAB_HOOK", "https://from-env")
    value = resolve_secret(layout, "LAB_HOOK")
    assert isinstance(value, SecretStr) and value.get_secret_value() == "https://from-env"
    assert "from-env" not in repr(value)


def test_file_is_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAB_HOOK", raising=False)
    layout = secrets_file(
        tmp_path, "# lab secrets\nexport LAB_HOOK='https://from-file'\n\nEMPTY=\n"
    )
    hook = resolve_secret(layout, "LAB_HOOK")
    assert hook is not None and hook.get_secret_value() == "https://from-file"
    assert resolve_secret(layout, "EMPTY") is None
    assert resolve_secret(layout, "MISSING") is None


def test_empty_environment_value_counts_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_HOOK", "")
    assert resolve_secret(Layout(tmp_path), "LAB_HOOK") is None


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_readable_secrets_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    monkeypatch.delenv("LAB_HOOK", raising=False)
    layout = secrets_file(tmp_path, "LAB_HOOK=SECRETXYZ\n", mode)
    with pytest.raises(SecretsFileError, match="chmod 600") as info:
        resolve_secret(layout, "LAB_HOOK")
    assert "SECRETXYZ" not in str(info.value)
    with pytest.raises(SecretsFileError):
        check_secrets_file(layout)


def test_malformed_line_names_the_line_not_the_value(tmp_path: Path) -> None:
    layout = secrets_file(tmp_path, "GOOD=1\nnot a pair SECRETXYZ\n")
    with pytest.raises(SecretsFileError, match="line 2") as info:
        check_secrets_file(layout)
    assert "SECRETXYZ" not in str(info.value)


def test_no_secrets_file_is_fine(tmp_path: Path) -> None:
    check_secrets_file(Layout(tmp_path))


def test_secret_env_names_cover_configured_and_default_names() -> None:
    settings = Settings(
        notify=NotifySettings(
            slack=SlackSettings(webhook_env="LAB_HOOK"),
            email=EmailSettings(
                host="127.0.0.1", sender="a@b.c", to=["a@b.c"], password_env="LAB_SMTP"
            ),
        )
    )
    names = secret_env_names(settings)
    assert {
        "LAB_HOOK", "LAB_SMTP", "HYPOTHEX_INDEX_PASSWORD", "HYPOTHEX_SLACK_WEBHOOK",
        "HYPOTHEX_SERVE_TOKEN", "HYPOTHEX_HUB_TOKEN",
    } <= names  # fmt: skip
    assert scrub_env({"LAB_HOOK": "x", "PATH": "/bin"}, names) == {"PATH": "/bin"}


def test_env_allowlist_never_holds_a_secret_name() -> None:
    for name in ENV_ALLOWLIST:
        assert not name.endswith(("_WEBHOOK", "_PASSWORD", "_TOKEN", "_SECRET")), name


@pytest.mark.parametrize(
    "text",
    [
        "digest: {timezone: SECRETXYZ}\n",
        "digest: *SECRETXYZ\n",
        "digest: !SECRETXYZ {}\n",
        "digest: [SECRETXYZ\n",
    ],
)
def test_parser_and_validator_messages_never_echo_secrets(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(write(tmp_path, text))
    assert "SECRETXYZ" not in str(info.value)
    assert info.value.__suppress_context__


def test_alias_cycle_names_its_line(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"cycle.*line 2"):
        load_settings(write(tmp_path, "notify: &n\n  default: *n\n"))


def test_shared_acyclic_aliases_are_supported(tmp_path: Path) -> None:
    settings = load_settings(
        write(
            tmp_path,
            "notify:\n  default: &rule {channels: [slack]}\n  projects: {a: *rule, b: *rule}\n",
        )
    )
    assert settings.notify.projects["a"] == settings.notify.projects["b"]


@pytest.mark.parametrize("name", ["lower", "WITH-DASH", " WITH_SPACE", "A" * 65, "A\n"])
def test_secret_variable_names_are_strict(tmp_path: Path, name: str) -> None:
    import yaml

    with pytest.raises(ConfigError, match="webhook_env"):
        load_settings(write(tmp_path, yaml.safe_dump({"notify": {"slack": {"webhook_env": name}}})))


def test_wrong_owner_secrets_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = secrets_file(tmp_path, "LAB_HOOK=SECRETXYZ\n")
    monkeypatch.setattr(os, "getuid", lambda: secrets_path(layout).stat().st_uid + 1)
    with pytest.raises(SecretsFileError, match="not yours") as info:
        check_secrets_file(layout)
    assert "SECRETXYZ" not in str(info.value)


def test_write_private_failure_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "home" / "private"
    write_private(path, "previous")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic"):
        write_private(path, "replacement")
    assert path.read_text() == "previous"
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "host, expected",
    [("localhost", True), ("[::1]", True), ("127.0.0.2", True), ("192.0.2.1", False)],
)
def test_loopback_detection(host: str, expected: bool) -> None:
    from hypothex.core.settings import is_loopback_host

    assert is_loopback_host(host) is expected


def test_password_detection_and_redaction_invalid_url() -> None:
    from hypothex.core.settings import url_holds_password

    assert url_holds_password("postgresql://[broken")
    assert redact_url("postgresql://[broken") == "***"
    assert not url_holds_password("postgresql://u@h/d?sslmode=require")
