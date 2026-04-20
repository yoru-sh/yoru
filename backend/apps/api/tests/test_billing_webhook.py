"""Unit tests for POST /api/v1/billing/webhook (US-16, Wave-20-C C2).

Covers HMAC verification, idempotency on replay, signature rejection, missing
header rejection, and unknown-event-type no-op. Bonus: 503 when secret unset.

Harness mirrors test_billing_checkout.py: in-memory SQLite + StaticPool, plus
a monkeypatch of `webhook.engine` because the webhook handler opens its own
`DBSession(engine)` (no Depends(get_session) injection).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from typing import Iterator

import pytest

os.environ.setdefault("RECEIPT_DB_URL", "sqlite:///:memory:")

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from apps.api.api.routers.billing import webhook as webhook_module  # noqa: E402
from apps.api.api.routers.billing.models import BillingEvent, Org  # noqa: E402
from apps.api.api.routers.billing.webhook import WebhookRouter  # noqa: E402
from apps.api.api.routers.receipt import db as receipt_db  # noqa: E402
from apps.api.api.routers.receipt import models  # noqa: F401,E402

_SECRET = "testsecret"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture()
def engine(monkeypatch):
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    # Webhook module imported `engine` at module-load → must monkeypatch the
    # bound name in the webhook namespace, not just receipt_db.engine.
    monkeypatch.setattr(webhook_module, "engine", eng)
    monkeypatch.setattr(receipt_db, "engine", eng)
    yield eng


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture()
def app(engine) -> FastAPI:
    _app = FastAPI()
    _app.include_router(WebhookRouter().get_router(), prefix="/api/v1/billing")
    return _app


@pytest.fixture()
def secret_env(monkeypatch):
    monkeypatch.setenv("POLAR_WEBHOOK_SECRET", _SECRET)


async def _post(app: FastAPI, body: bytes, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.post("/api/v1/billing/webhook", content=body, headers=headers)


async def test_webhook_checkout_completed_flips_plan(
    app, db_session, secret_env
) -> None:
    org_id = str(uuid.uuid4())
    payload = {
        "id": "evt_1",
        "type": "checkout.completed",
        "data": {"client_reference_id": org_id, "plan": "team"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Polar-Signature": _sign(body), "Content-Type": "application/json"}

    resp = await _post(app, body, headers)
    assert resp.status_code == 200, resp.text

    org = db_session.get(Org, org_id)
    assert org is not None, "org row missing after checkout.completed"
    assert org.plan == "team"

    evt = db_session.get(BillingEvent, "evt_1")
    assert evt is not None, "billing_events row missing"
    assert evt.event_type == "checkout.completed"
    assert evt.org_id == org_id


async def test_webhook_idempotent_on_replay(app, db_session, secret_env) -> None:
    org_id = str(uuid.uuid4())
    payload = {
        "id": "evt_1",
        "type": "checkout.completed",
        "data": {"client_reference_id": org_id, "plan": "team"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Polar-Signature": _sign(body), "Content-Type": "application/json"}

    resp1 = await _post(app, body, headers)
    assert resp1.status_code == 200, resp1.text

    # Mutate DB to detect a second mutation: flip plan to a sentinel and assert
    # the replay does NOT re-apply "team" over the sentinel.
    org = db_session.get(Org, org_id)
    org.plan = "sentinel_after_first"
    db_session.add(org)
    db_session.commit()

    resp2 = await _post(app, body, headers)
    assert resp2.status_code == 200, resp2.text

    db_session.expire_all()
    org = db_session.get(Org, org_id)
    assert org.plan == "sentinel_after_first", (
        "replay re-applied mutation; idempotency broken"
    )

    rows = db_session.exec(
        select(BillingEvent).where(BillingEvent.event_id == "evt_1")
    ).all()
    assert len(rows) == 1, f"expected 1 BillingEvent for evt_1, got {len(rows)}"


async def test_webhook_rejects_bad_signature(app, db_session, secret_env) -> None:
    org_id = str(uuid.uuid4())
    payload = {
        "id": "evt_bad_sig",
        "type": "checkout.completed",
        "data": {"client_reference_id": org_id, "plan": "team"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-Polar-Signature": _sign(body, "not-the-secret"),
        "Content-Type": "application/json",
    }

    resp = await _post(app, body, headers)
    assert resp.status_code == 400, resp.text

    assert db_session.get(BillingEvent, "evt_bad_sig") is None
    assert db_session.get(Org, org_id) is None


async def test_webhook_rejects_missing_signature_header(
    app, db_session, secret_env
) -> None:
    org_id = str(uuid.uuid4())
    payload = {
        "id": "evt_no_sig",
        "type": "checkout.completed",
        "data": {"client_reference_id": org_id, "plan": "team"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    resp = await _post(app, body, headers)
    assert resp.status_code == 400, resp.text

    assert db_session.get(BillingEvent, "evt_no_sig") is None
    assert db_session.get(Org, org_id) is None


async def test_webhook_unknown_event_type_is_noop(
    app, db_session, secret_env
) -> None:
    payload = {"id": "evt_2", "type": "bogus.event.kind", "data": {}}
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Polar-Signature": _sign(body), "Content-Type": "application/json"}

    resp = await _post(app, body, headers)
    assert resp.status_code == 200, resp.text

    assert db_session.get(BillingEvent, "evt_2") is None
    org_count = len(db_session.exec(select(Org)).all())
    assert org_count == 0, f"unknown event type mutated org table (got {org_count} rows)"


async def test_webhook_503_when_secret_unset(app, db_session, monkeypatch) -> None:
    monkeypatch.delenv("POLAR_WEBHOOK_SECRET", raising=False)
    payload = {"id": "evt_x", "type": "checkout.completed", "data": {}}
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Polar-Signature": _sign(body), "Content-Type": "application/json"}

    resp = await _post(app, body, headers)
    assert resp.status_code == 503, resp.text
