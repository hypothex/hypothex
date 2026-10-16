import logging
from email.message import EmailMessage

import pytest
from pydantic import SecretStr

from hypothex.core.settings import EmailSettings
from hypothex.notify.channels import ChannelError, redact, send_email, send_slack
from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply


def message() -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "✓ toy r1", "hx@lab.org", "sv@lab.org"
    msg.set_content("line\n")
    return msg


def email(smtp: FakeSmtp, **over: object) -> EmailSettings:
    base: dict[str, object] = {
        "host": "127.0.0.1",
        "port": smtp.port,
        "security": "none",
        "password_env": None,
        "sender": "hx@lab.org",
        "to": ["sv@lab.org"],
        "timeout": 5,
    }
    return EmailSettings.model_validate({**base, **over})


def test_slack_ok() -> None:
    with FakeWebhook() as hook:
        send_slack(SecretStr(hook.url), {"text": "✓ toy"})
        assert hook.requests[0]["body"] == {"text": "✓ toy"}


@pytest.mark.parametrize(
    ("reply", "error_class", "permanent", "retry_after"),
    [
        (Reply(429, retry_after=7), "http_429", False, 7.0),
        (Reply(500), "http_500", False, None),
        (Reply(503), "http_503", False, None),
        (Reply(404), "http_404", True, None),
        (Reply(410), "http_410", True, None),
    ],
)
def test_slack_errors(
    reply: Reply, error_class: str, permanent: bool, retry_after: float | None
) -> None:
    with FakeWebhook([reply]) as hook:
        with pytest.raises(ChannelError) as info:
            send_slack(SecretStr(hook.url), {"text": "x"})
        exc = info.value
        assert (exc.error_class, exc.permanent, exc.retry_after) == (
            error_class,
            permanent,
            retry_after,
        )
        assert str(exc) == error_class and hook.secret not in str(exc)
        assert exc.__cause__ is None and exc.__suppress_context__


def test_slack_url_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with FakeWebhook() as hook:
        send_slack(SecretStr(hook.url), {"text": "x"})
    assert hook.secret not in caplog.text


def test_slack_timeout_is_retryable() -> None:
    with FakeWebhook([Reply(stall=2.0)]) as hook, pytest.raises(ChannelError) as info:
        send_slack(SecretStr(hook.url), {"text": "x"}, timeout=0.3)
    assert info.value.error_class == "timeout" and not info.value.permanent


def test_plain_http_off_loopback_is_refused_without_a_request() -> None:
    with pytest.raises(ChannelError) as info:
        send_slack(SecretStr("http://hooks.example.com/services/T/B/SECRET"), {"text": "x"})
    assert info.value.error_class == "insecure_webhook" and info.value.permanent


@pytest.mark.parametrize("mode", ["plain", "starttls", "ssl"])
def test_email_ok_in_every_mode(mode: str) -> None:
    security = {"plain": "none", "starttls": "starttls", "ssl": "ssl"}[mode]
    with FakeSmtp(mode=mode, user="sv", password="pw") as smtp:  # type: ignore[arg-type]
        settings = email(smtp, security=security, username="sv")
        send_email(settings, SecretStr("pw"), message(), ssl_context=smtp.client_context)
        assert smtp.received[0].message["Subject"] == "✓ toy r1"


@pytest.mark.parametrize(
    ("fail", "error_class", "permanent"),
    [
        ("auth", "smtp_535", True),
        ("data_451", "smtp_451", False),
        ("data_550", "smtp_550", True),
        ("connect_421", "smtp_421", False),
    ],
)
def test_email_errors(fail: str, error_class: str, permanent: bool) -> None:
    with FakeSmtp(user="sv", password="pw", fail=fail) as smtp:  # type: ignore[arg-type]
        with pytest.raises(ChannelError) as info:
            send_email(email(smtp, username="sv"), SecretStr("pw"), message())
        assert (info.value.error_class, info.value.permanent) == (error_class, permanent)
        assert "pw" not in str(info.value)


def test_email_stall_times_out() -> None:
    with FakeSmtp(fail="stall") as smtp, pytest.raises(ChannelError) as info:
        send_email(email(smtp, timeout=0.5), None, message())
    assert (info.value.error_class, info.value.permanent) == ("timeout", False)


def test_starttls_missing_is_permanent() -> None:
    with FakeSmtp() as smtp, pytest.raises(ChannelError) as info:
        send_email(email(smtp, security="starttls"), None, message())
    assert (info.value.error_class, info.value.permanent) == ("smtp_no_starttls", True)


def test_redact_values_and_webhook_paths() -> None:
    hook = "https://hooks.slack.com/services/T0/B0/SECRETXYZ"
    text = f"POST {hook} failed; path /services/T0/B0/SECRETXYZ; pw hunter2"
    assert redact(text, [SecretStr(hook), "hunter2", None]) == "POST *** failed; path ***; pw ***"


@pytest.mark.parametrize("header", ["nan", "inf", "-1", "garbage"])
def test_invalid_retry_after_is_ignored(header: str) -> None:
    import httpx

    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": header})
    )
    with pytest.raises(ChannelError) as info:
        send_slack(SecretStr("https://hooks.example/services/A/B/SECRET"), {}, transport=transport)
    assert info.value.retry_after is None


def test_overlapping_secrets_are_redacted_longest_first() -> None:
    assert redact("PASSWORDLONG PASSWORD", ["PASSWORD", "PASSWORDLONG"]) == "*** ***"


def test_child_http_logger_cannot_leak_a_webhook(caplog: pytest.LogCaptureFixture) -> None:
    import httpx

    url = "https://hooks.example/services/A/B/SECRETLOG"

    def transport(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpcore.new.child").debug("sending %s", request.url)
        return httpx.Response(200)

    caplog.set_level(logging.DEBUG)
    send_slack(SecretStr(url), {}, transport=httpx.MockTransport(transport))
    assert "SECRETLOG" not in caplog.text


def test_untrusted_smtp_certificate_is_permanent() -> None:
    with FakeSmtp(mode="ssl") as smtp, pytest.raises(ChannelError) as info:
        send_email(email(smtp, security="ssl"), None, message())
    assert (info.value.error_class, info.value.permanent) == ("tls", True)


@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize(
    ("codes", "error_class", "permanent"),
    [
        ([450], "smtp_450", False),
        ([550], "smtp_550", True),
        ([550, 450], "smtp_450", False),
        ([551, 550], "smtp_550", True),
    ],
)
def test_smtp_recipient_refusals_never_report_full_success(
    accepted: bool, codes: list[int], error_class: str, permanent: bool
) -> None:
    refusals = {
        f"SECRETRECIPIENT{i}@lab.invalid": (code, "SECRETSMTPREPLY") for i, code in enumerate(codes)
    }
    recipients = (["accepted@lab.invalid"] if accepted else []) + list(refusals)
    with FakeSmtp(refusals=refusals) as smtp:
        msg = message()
        msg.replace_header("To", ", ".join(recipients))
        with pytest.raises(ChannelError) as info:
            send_email(email(smtp, to=recipients), None, msg)
        assert (info.value.error_class, info.value.permanent) == (error_class, permanent)
        assert str(info.value) == error_class
        assert info.value.__cause__ is None and info.value.__suppress_context__
        assert len(smtp.received) == int(accepted)
        if accepted:
            assert smtp.received[0].rcpt_tos == ["accepted@lab.invalid"]
