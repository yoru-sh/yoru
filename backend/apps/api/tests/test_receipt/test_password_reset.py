"""Tests for the password-reset plumbing (wave-14 C4).

The endpoints ship as flag-gated stubs:
- `AUTH_PASSWORD_RESET_ENABLED` off (default) → both 404
- flag on → request issues a 1-hour token; confirm consumes it (401 on
  expired / already-used / unknown-hash)

Delivery (email) and password storage itself are deliberately out of
scope — see vault/audits/auth-password-reset-design.md.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession, select

from apps.api.api.routers.receipt.auth_router import _RESET_TOKEN_PREFIX
from apps.api.api.routers.receipt.deps import _naive_utc_now
from apps.api.api.routers.receipt.models import PasswordResetToken


_FLAG = "AUTH_PASSWORD_RESET_ENABLED"


def test_password_reset_request_flag_off_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    resp = client.post(
        "/api/v1/auth/password-reset-request",
        json={"email": "alice@example.com"},
    )
    assert resp.status_code == 404, resp.text


def test_password_reset_request_flag_on_returns_202(
    client: TestClient, engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_FLAG, "true")
    resp = client.post(
        "/api/v1/auth/password-reset-request",
        json={"email": "bob@example.com"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"sent": True}

    # Exactly one row, bound to the submitted email, expiring ~1h out.
    with DBSession(engine) as s:
        rows = s.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.user_email == "bob@example.com"
            )
        ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.used_at is None
    delta = row.expires_at - row.issued_at
    assert timedelta(minutes=55) <= delta <= timedelta(minutes=65)


def test_password_reset_confirm_flag_off_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    resp = client.post(
        "/api/v1/auth/password-reset-confirm",
        json={"token": "rcpt_reset_whatever", "new_password": "NewSecret1!"},
    )
    assert resp.status_code == 404, resp.text


def test_password_reset_confirm_expired_token_401(
    client: TestClient, engine, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_FLAG, "true")

    # Hand-craft an expired token row directly — avoids a sleep and keeps the
    # test deterministic.
    raw = _RESET_TOKEN_PREFIX + "expired-fixture-token"
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = _naive_utc_now()
    row = PasswordResetToken(
        id="expiredrow",
        user_email="carol@example.com",
        token_hash=token_hash,
        issued_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    db_session.add(row)
    db_session.commit()

    resp = client.post(
        "/api/v1/auth/password-reset-confirm",
        json={"token": raw, "new_password": "irrelevant"},
    )
    assert resp.status_code == 401, resp.text

    # Expired rows remain unused (not double-consumed by the 401 branch).
    with DBSession(engine) as s:
        refreshed = s.get(PasswordResetToken, "expiredrow")
    assert refreshed is not None and refreshed.used_at is None
