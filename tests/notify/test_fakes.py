import smtplib
from email.message import EmailMessage

import httpx
import pytest

from tests.fakes.smtp import Failure, FakeSmtp, Mode
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
def test_scripted_data_failures(fail: Failure, code: int) -> None:
    with FakeSmtp(fail=fail) as smtp:
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


@pytest.mark.parametrize("mode", ["plain", "starttls", "ssl"])
def test_smtp_greeting_never_uses_the_machine_resolver(
    mode: Mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def unexpected_lookup(name: str = "") -> str:
        raise AssertionError("fake SMTP greeting must not resolve the machine hostname")

    monkeypatch.setattr(socket, "getfqdn", unexpected_lookup)
    fake = FakeSmtp(mode=mode, user="sv", password="pw")
    try:
        with fake as smtp:
            if mode == "ssl":
                client = smtplib.SMTP_SSL(
                    "127.0.0.1",
                    smtp.port,
                    timeout=5,
                    local_hostname="localhost",
                    context=smtp.client_context,
                )
            else:
                client = smtplib.SMTP("127.0.0.1", smtp.port, timeout=5, local_hostname="localhost")
            with client:
                if mode == "starttls":
                    client.starttls(context=smtp.client_context)
                client.login("sv", "pw")
                client.send_message(message("without DNS"))
            assert smtp.received[0].message["Subject"] == "without DNS"
            assert smtp._controller is not None and smtp._controller.smtpd is not None
            assert smtp._controller.smtpd.hostname == "localhost"
    finally:
        if fake._controller is not None:
            fake.stop()  # also release resources when testing the pre-fix failure


@pytest.mark.parametrize("stage", ["trigger", "factory", "bind"])
def test_failed_smtp_start_closes_its_thread_loop_and_listener(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    from typing import Any

    from aiosmtpd.controller import Controller

    import tests.fakes.smtp as smtp_module

    controllers: list[Controller] = []

    def controller(*args: Any, **kwargs: Any) -> Controller:
        made = Controller(*args, **kwargs)
        controllers.append(made)
        return made

    def fail(self: Controller) -> None:
        raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(smtp_module, "Controller", controller)
    if stage != "bind":
        monkeypatch.setattr(
            Controller, "_trigger_server" if stage == "trigger" else "factory", fail
        )
    fake = FakeSmtp()
    with socket.socket() as occupied:
        if stage == "bind":
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            fake.port = occupied.getsockname()[1]
        try:
            with pytest.raises(OSError if stage == "bind" else RuntimeError):
                fake.start()
            (made,) = controllers
            assert made._thread is None, "failed startup left the controller thread behind"
            assert made.loop.is_closed(), "failed startup left the event loop open"
            assert fake._controller is None
            if stage != "bind":
                with socket.socket() as probe:
                    probe.settimeout(0.2)
                    assert probe.connect_ex(("127.0.0.1", fake.port)) != 0
            fake.stop()  # cleanup remains safe after the failed start already cleaned up
        finally:
            for made in controllers:
                if made._thread is not None:
                    made.stop(no_assert=True)
                if not made.loop.is_closed():
                    made.loop.close()
