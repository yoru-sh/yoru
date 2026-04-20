"""Integration-test harness — hits the live uvicorn pid on :8002.

Fixtures:
  * `client`       — httpx.AsyncClient pointed at RECEIPT_INTEGRATION_URL
                     (default http://localhost:8002). Fails loudly if the
                     backend isn't reachable (no silent skip).
  * `clean_db`     — autouse; truncates events → sessions → hook_tokens
                     before every test so each test sees a pristine DB.
  * `authed_client`— mints a fresh hook-token via
                     POST /api/v1/auth/hook-token and returns
                     (client, user_email, token) with the Bearer header set.

Unit tests live in the parent directory; this package is selected with
`-m integration` and excluded from default runs via pyproject addopts.
"""
from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
from sqlmodel import SQLModel

from apps.api.api.routers.receipt.db import engine


def _base_url() -> str:
    return os.environ.get("RECEIPT_INTEGRATION_URL", "http://localhost:8002")


@pytest.fixture(autouse=True)
def clean_db():
    """Truncate receipt tables before each test.

    Order matters: events has a FK to sessions, so events must go first.
    hook_tokens is independent but listed last to match the brief.
    Untouched: any non-receipt table (alembic, SaaSForge residue, etc.).
    """
    tables = ("events", "sessions", "hook_tokens")
    with engine.begin() as conn:
        for name in tables:
            tbl = SQLModel.metadata.tables.get(name)
            if tbl is not None:
                conn.execute(tbl.delete())
    yield


@pytest.fixture
async def client():
    base_url = _base_url()
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as c:
        try:
            r = await c.get("/health")
        except httpx.TransportError as exc:
            raise RuntimeError(
                f"backend not reachable at {base_url}: {exc}. "
                f"Start it with `make restart-backend` or set RECEIPT_INTEGRATION_URL."
            ) from exc
        if r.status_code != 200:
            raise RuntimeError(
                f"backend not healthy at {base_url}: /health -> {r.status_code}"
            )
        yield c


@pytest.fixture
async def authed_client(client, clean_db):
    """Mint a fresh hook-token for an isolated integ user and attach bearer."""
    user = f"integ-{uuid4().hex[:8]}@test.local"
    r = await client.post("/api/v1/auth/hook-token", json={"user": user})
    r.raise_for_status()
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        yield client, user, token
    finally:
        client.headers.pop("Authorization", None)
