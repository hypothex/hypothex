import smtplib
from email.message import EmailMessage

import httpx
import pytest

from tests.fakes.smtp import FakeSmtp
from tests.fakes.webhook import FakeWebhook, Reply


def message(subject: str = "hi") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, "hx@lab.org", "sv@lab.org"
    msg.set_content("body\n")
    return msg


def test_webhook_records_and_plays_its_script() -> None:
    with FakeWebhook([Reply(429, retry_after=7), Reply(500)]) as hook:
        assert hook.url.startswith("http://127.0.0.1:")
        assert "/services/T000/B000/SECRETHOOK" in hook.url
        first = httpx.post(hook.url, json={"text": "a"})
        assert first.status_code == 429 and first.headers["Retry-After"] == "7"
        assert httpx.post(hook.url, json={"text": "b"}).status_code == 500
        assert httpx.post(hook.url, json={"text": "c"}).status_code == 200
        assert [r["body"]["text"] for r in hook.requests] == ["a", "b", "c"]


def test_webhook_stall_times_the_client_out() -> None:
    with FakeWebhook([Reply(stall=2.0)]) as hook, pytest.raises(httpx.TimeoutException):
        httpx.post(hook.url, json={}, timeout=0.3)


def test_plain_smtp_receives() -> None:
    with FakeSmtp() as smtp, smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
        client.send_message(message("plain"))
    assert smtp.received[0].message["Subject"] == "plain"
    assert smtp.received[0].rcpt_tos == ["sv@lab.org"]


def test_starttls_with_login() -> None:
    with FakeSmtp(mode="starttls", user="sv", password="pw") as smtp:
        with smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
            client.starttls(context=smtp.client_context)
            client.login("sv", "pw")
            client.send_message(message("tls"))
        assert smtp.received[0].message["Subject"] == "tls"


def test_implicit_ssl() -> None:
    with FakeSmtp(mode="ssl") as smtp:
        with smtplib.SMTP_SSL(
            "127.0.0.1", smtp.port, timeout=5, context=smtp.client_context
        ) as client:
            client.send_message(message("ssl"))
        assert smtp.received[0].message["Subject"] == "ssl"


def test_wrong_password_is_535() -> None:
    with FakeSmtp(user="sv", password="pw") as smtp, smtplib.SMTP("127.0.0.1", smtp.port) as c:
        with pytest.raises(smtplib.SMTPAuthenticationError) as info:
            c.login("sv", "nope")
        assert info.value.smtp_code == 535


@pytest.mark.parametrize(("fail", "code"), [("data_451", 451), ("data_550", 550)])
def test_scripted_data_failures(fail: str, code: int) -> None:
    with FakeSmtp(fail=fail) as smtp:  # type: ignore[arg-type]
        with smtplib.SMTP("127.0.0.1", smtp.port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPDataError) as info:
                client.send_message(message())
            assert info.value.smtp_code == code
        assert smtp.received == []


def test_connect_421_and_stall() -> None:
    with FakeSmtp(fail="connect_421") as smtp, pytest.raises(smtplib.SMTPConnectError) as info:
        smtplib.SMTP("127.0.0.1", smtp.port, timeout=5)
    assert info.value.smtp_code == 421
    # smtplib turns a read timeout during the greeting into SMTPServerDisconnected
    with (
        FakeSmtp(fail="stall") as smtp,
        pytest.raises(smtplib.SMTPServerDisconnected, match="timed out"),
    ):
        smtplib.SMTP("127.0.0.1", smtp.port, timeout=0.5)
