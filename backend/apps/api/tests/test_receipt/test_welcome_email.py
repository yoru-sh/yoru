"""Tests for the welcome-email path (wave-54 ACTIVATION Hour-0).

Coverage:
  - stub mode logs `[WELCOME-EMAIL-STUB]` when SMTP_HOST is unset
  - SMTP mode opens an smtplib.SMTP connection and calls send_message once
  - the /auth/welcome-email endpoint is idempotent inside the dedupe window
  - the User row gains a welcome_email_sent_at stamp on first call
  - missing bearer → 401 (auth required)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from apps.api.api.routers.receipt.deps import _naive_utc_now
from apps.api.api.routers.receipt.email.welcome import send_welcome_email
from apps.api.api.routers.receipt.models import User

# ---------- send_welcome_email() unit tests ----------

def test_send_welcome_email_stub_logs_when_smtp_host_unset(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    caplog.set_level(logging.INFO, logger="apps.api.api.routers.receipt.email.welcome")

    send_welcome_email("user@example.com")

    matches = [r for r in caplog.records if "[WELCOME-EMAIL-STUB]" in r.getMessage()]
    assert matches, "stub branch must log [WELCOME-EMAIL-STUB] line"
    msg = matches[0].getMessage()
    assert "to=user@example.com" in msg
    # Body must carry the install snippet so log scrapers can replay if needed.
    assert "pip install receipt-cli" in msg
    assert "receipt init" in msg
    assert "claude" in msg


def test_send_welcome_email_smtp_mode_calls_send_message_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    fake_smtp_instance = MagicMock()
    fake_smtp_cm = MagicMock()
    fake_smtp_cm.__enter__.return_value = fake_smtp_instance
    fake_smtp_cm.__exit__.return_value = False

    with patch(
        "apps.api.api.routers.receipt.email.welcome.smtplib.SMTP",
        return_value=fake_smtp_cm,
    ) as smtp_ctor:
        send_welcome_email("alice@example.com")

    smtp_ctor.assert_called_once_with("smtp.example.com", 2525)
    fake_smtp_instance.send_message.assert_called_once()
    # STARTTLS disabled in this test → starttls() must NOT have been called.
    fake_smtp_instance.starttls.assert_not_called()
    # No creds set → login() must NOT have been called.
    fake_smtp_instance.login.assert_not_called()

    sent_msg = fake_smtp_instance.send_message.call_args.args[0]
    assert sent_msg["To"] == "alice@example.com"
    assert "Receipt" in sent_msg["Subject"]
    assert "alice@example.com" in sent_msg.get_content()


def test_send_welcome_email_smtp_mode_with_credentials_starts_tls_and_logs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "ses-user")
    monkeypatch.setenv("SMTP_PASSWORD", "ses-secret")
    monkeypatch.delenv("SMTP_STARTTLS", raising=False)  # default = true

    fake_smtp_instance = MagicMock()
    fake_smtp_cm = MagicMock()
    fake_smtp_cm.__enter__.return_value = fake_smtp_instance
    fake_smtp_cm.__exit__.return_value = False

    with patch(
        "apps.api.api.routers.receipt.email.welcome.smtplib.SMTP",
        return_value=fake_smtp_cm,
    ):
        send_welcome_email("bob@example.com")

    fake_smtp_instance.starttls.assert_called_once()
    fake_smtp_instance.login.assert_called_once_with("ses-user", "ses-secret")
    fake_smtp_instance.send_message.assert_called_once()


# ---------- /api/v1/auth/welcome-email endpoint tests ----------

def test_welcome_email_endpoint_requires_bearer(client) -> None:
    r = client.post("/api/v1/auth/welcome-email")
    assert r.status_code == 401


def test_welcome_email_endpoint_first_call_sends_and_stamps(
    client, db_session, mint_token, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    _, headers = mint_token("alice@example.com")

    with patch(
        "apps.api.api.routers.receipt.auth_router.send_welcome_email"
    ) as fake_send:
        r = client.post("/api/v1/auth/welcome-email", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    assert body["user_email"] == "alice@example.com"
    assert body["welcome_email_sent_at"] is not None
    fake_send.assert_called_once_with("alice@example.com")

    row = db_session.get(User, "alice@example.com")
    assert row is not None
    assert row.welcome_email_sent_at is not None


def test_welcome_email_endpoint_second_call_is_noop_within_window(
    client, db_session, mint_token, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    _, headers = mint_token("carol@example.com")

    with patch(
        "apps.api.api.routers.receipt.auth_router.send_welcome_email"
    ) as fake_send:
        first = client.post("/api/v1/auth/welcome-email", headers=headers)
        second = client.post("/api/v1/auth/welcome-email", headers=headers)

    assert first.status_code == 200 and first.json()["sent"] is True
    assert second.status_code == 200 and second.json()["sent"] is False
    # send_welcome_email must have been called exactly once across both requests.
    fake_send.assert_called_once_with("carol@example.com")
    # The stamp must NOT advance on the dedupe path.
    assert second.json()["welcome_email_sent_at"] == first.json()["welcome_email_sent_at"]


def test_welcome_email_endpoint_resends_after_dedupe_window(
    client, db_session, mint_token, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale stamp (>5min ago) does NOT block a re-send. Future hardening
    might change this, but the brief acceptance scopes idempotency to the
    5-min window — outside it the endpoint sends again."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    _, headers = mint_token("dave@example.com")

    stale = _naive_utc_now() - timedelta(minutes=10)
    db_session.add(User(email="dave@example.com", welcome_email_sent_at=stale))
    db_session.commit()

    with patch(
        "apps.api.api.routers.receipt.auth_router.send_welcome_email"
    ) as fake_send:
        r = client.post("/api/v1/auth/welcome-email", headers=headers)

    assert r.status_code == 200
    assert r.json()["sent"] is True
    fake_send.assert_called_once_with("dave@example.com")
