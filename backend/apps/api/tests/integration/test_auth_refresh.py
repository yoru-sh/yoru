"""E2E refresh-rotation test — wave-53 C2.

Proves the refresh-token rotation flow end-to-end through HTTP:
old refresh cookie is rejected after a successful refresh, and the
freshly-rotated refresh cookie lets the caller rotate again.

Spec anchors: vault/AUTH-HARDENING-V1.md §3 (rotation-on-use) + §4
(reuse-detection) + §6 (test matrix). Implementation:
`apps/api/api/routers/receipt/auth_router.py:267-394`.

Scope notes (brief asked for register → login → expired-access →
refresh → protected-route; the deployed surface differs):

1. `/api/v1/auth/register` and `/api/v1/auth/login` are NOT mounted —
   Receipt's hook-token flow is the deployed login proxy
   (`test_e2e_v1_auth.py:5-14`). We seed an `AuthSession` row directly
   as the login proxy (same pattern as the unit `test_refresh.py`).
2. The JWT access token minted by `/auth/refresh` has no consumer —
   `require_current_user` (deps.py:84-94) accepts `rcpt_*` hook-tokens
   only, so "call the protected route with the new access token" has
   nowhere to land today. The rotation guarantee (old refresh
   rejected, new refresh accepted) is exercised via `/auth/refresh`
   itself, which IS the enforcement point for the rotation contract.
3. Access-TTL expiry (`time.sleep(1.1)`) is moot here — there is no
   JWT-accepting route to fail against. Skipping the sleep keeps the
   test under 100 ms.

Isolation: autouse `clean_db` from conftest.py truncates the *live*
backend DB (it hits `backend/data/receipt.db` via the module-level
engine). This module OVERRIDES it with a no-op so the test is
hermetic. Each test gets a fresh in-memory engine via the `engine`
fixture below.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from apps.api.api.routers.receipt import db as receipt_db  # noqa: F401
from apps.api.api.routers.receipt import models  # noqa: F401
from apps.api.api.routers.receipt.auth_router import AuthRouter
from apps.api.api.routers.receipt.auth_sessions_model import AuthSession
from apps.api.api.routers.receipt.db import get_session


@pytest.fixture(autouse=True)
def clean_db():
    """Override conftest.clean_db — it truncates the live receipt DB.

    Hermetic isolation here is the per-test in-memory engine; no
    truncation needed.
    """
    yield


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture()
def client(engine) -> TestClient:
    app = FastAPI()
    app.include_router(AuthRouter().get_router(), prefix="/api/v1")

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def _seed_login(db_session: Session, user_email: str) -> str:
    """Mint an `AuthSession` row and return the raw refresh token.

    Stand-in for `/api/v1/auth/login` (not mounted — see module
    docstring). Shape matches what the auth_router.refresh handler
    expects on the happy path: live, non-revoked, future expiry.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).replace(tzinfo=None)
    db_session.add(
        AuthSession(
            id=uuid.uuid4().hex,
            user_email=user_email,
            refresh_token_hash=token_hash,
            issued_at=now,
            expires_at=now + timedelta(days=30),
            family_id=uuid.uuid4().hex,
        )
    )
    db_session.commit()
    return raw


def test_refresh_rotation_old_rejected_new_accepted(
    client: TestClient, db_session: Session
) -> None:
    """Old refresh cookie → 401 after rotation; new refresh cookie → 200.

    Order matters: we verify the new cookie works BEFORE replaying the
    old one. AUTH-HARDENING-V1 §4 reuse detection revokes every live
    row in the family when a revoked token is replayed — including
    children of the original rotation. Using the new cookie first
    isolates "new is accepted" from the family-sweep side effect.
    """
    old_refresh = _seed_login(db_session, "alice@example.com")

    # 1st rotation — mints a new refresh + access pair, revokes the old row.
    r1 = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}
    )
    assert r1.status_code == 200, r1.text
    new_refresh = r1.json()["refresh_token"]
    assert new_refresh and new_refresh != old_refresh

    # New refresh cookie rotates successfully — proves "new is accepted".
    r2 = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": new_refresh}
    )
    assert r2.status_code == 200, r2.text

    # Replay old cookie — reuse-detected, 401 auth_revoked.
    r3 = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}
    )
    assert r3.status_code == 401 and r3.json() == {"error": "auth_revoked"}
