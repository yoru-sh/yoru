"""Unit tests for POST /api/v1/billing/checkout-session (US-15, Wave-20-B C2).

Follows the test_receipt/ pattern: in-memory SQLite + AuthRouter for bearer
minting + monkeypatched module-level _polar_client so the Polar SDK is never
touched. Async via pytest-asyncio (auto mode) + httpx.AsyncClient + ASGITransport.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from typing import Iterator
from unittest.mock import MagicMock

import pytest

# Point the receipt DB at in-memory sqlite BEFORE importing the package.
os.environ.setdefault("RECEIPT_DB_URL", "sqlite:///:memory:")

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from apps.api.api.routers.billing import checkout as checkout_module  # noqa: E402
from apps.api.api.routers.billing.checkout import CheckoutRouter  # noqa: E402
from apps.api.api.routers.receipt import db as receipt_db  # noqa: E402
from apps.api.api.routers.receipt import models  # noqa: F401,E402
from apps.api.api.routers.receipt.auth_router import AuthRouter  # noqa: E402
from apps.api.api.routers.receipt.db import get_session  # noqa: E402
from apps.api.api.routers.receipt.models import HookToken  # noqa: E402


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    old = receipt_db.engine
    receipt_db.engine = eng
    try:
        yield eng
    finally:
        receipt_db.engine = old


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture()
def app(engine) -> FastAPI:
    _app = FastAPI()
    _app.include_router(CheckoutRouter().get_router(), prefix="/api/v1/billing")
    _app.include_router(AuthRouter().get_router(), prefix="/api/v1")

    def _override():
        with Session(engine) as s:
            yield s

    _app.dependency_overrides[get_session] = _override
    return _app


@pytest.fixture()
def mint_token(db_session):
    """Factory: mint_token('alice') → (raw_token, headers_with_bearer)."""
    def _mint(user: str):
        raw = f"rcpt_{secrets.token_urlsafe(24)}"
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = HookToken(id=uuid.uuid4().hex, user=user, token_hash=token_hash)
        db_session.add(row)
        db_session.commit()
        return raw, {"Authorization": f"Bearer {raw}"}

    return _mint


@pytest.fixture()
def mock_polar(monkeypatch):
    """Replace the module-level `_polar_client` with a MagicMock whose
    `.checkouts.create(...)` returns a canned response."""
    mock_response = MagicMock(url="https://polar.test/checkout/abc", id="cs_mock_abc")
    client = MagicMock()
    client.checkouts.create.return_value = mock_response
    monkeypatch.setattr(checkout_module, "_polar_client", client)
    return client


async def test_checkout_happy_path_team_plan(app, mint_token, mock_polar) -> None:
    _, headers = mint_token("alice@test.local")
    body = {
        "plan": "team",
        "success_url": "http://localhost/ok",
        "cancel_url": "http://localhost/no",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/billing/checkout-session", json=body, headers=headers
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["checkout_url"] == "https://polar.test/checkout/abc"
    assert payload["session_id"] == "cs_mock_abc"

    assert mock_polar.checkouts.create.call_count == 1
    call_kwargs = mock_polar.checkouts.create.call_args.kwargs
    # org_id is derived from the user string via uuid5; we only assert the
    # handler passed *something* as client_reference_id and it's a str of a UUID.
    org_ref = call_kwargs["client_reference_id"]
    assert isinstance(org_ref, str)
    uuid.UUID(org_ref)  # raises ValueError if not a valid UUID
    assert call_kwargs["success_url"] == "http://localhost/ok"
    assert call_kwargs["cancel_url"] == "http://localhost/no"


async def test_checkout_invalid_plan_returns_400(app, mint_token, mock_polar) -> None:
    _, headers = mint_token("bob@test.local")
    body = {
        "plan": "enterprise_ultra",
        "success_url": "http://localhost/ok",
        "cancel_url": "http://localhost/no",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/billing/checkout-session", json=body, headers=headers
        )

    assert resp.status_code == 400, resp.text
    # The error envelope is shaped either {"detail": "..."} (FastAPI default) or
    # {"error": {"message": "..."}} (custom envelope middleware). Match both by
    # searching the stringified payload.
    text = resp.text.lower()
    assert "unknown plan" in text or "invalid plan" in text
    mock_polar.checkouts.create.assert_not_called()


async def test_checkout_unauth_returns_401(app, mock_polar) -> None:
    body = {
        "plan": "team",
        "success_url": "http://localhost/ok",
        "cancel_url": "http://localhost/no",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/billing/checkout-session", json=body)

    assert resp.status_code == 401, resp.text
    mock_polar.checkouts.create.assert_not_called()
