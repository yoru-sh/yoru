"""Wave-25-C4 — US-15 billing checkout integration smoke.

Hits the LIVE backend at RECEIPT_INTEGRATION_URL (default http://localhost:8002).
The Polar SDK is stubbed module-side via `_polar_client = MagicMock()` as long
as `POLAR_API_KEY` is unset in the uvicorn process env, so these tests exercise
the real FastAPI routing + auth dep without touching Polar.

Contract refs: BACKEND-API-V1.md §4.1 + apps/api/api/routers/billing/checkout.py.
"""
from __future__ import annotations

import httpx
import pytest


_VALID_BODY = {
    "plan": "team",
    "success_url": "https://localhost/ok",
    "cancel_url": "https://localhost/no",
}


@pytest.mark.integration
async def test_checkout_session_live_happy_path(authed_client):
    client, _user, _token = authed_client

    resp = await client.post("/api/v1/billing/checkout-session", json=_VALID_BODY)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "checkout_url" in body and isinstance(body["checkout_url"], str)
    assert "session_id" in body and isinstance(body["session_id"], str)
    assert body["checkout_url"]
    assert body["session_id"]


@pytest.mark.integration
async def test_checkout_session_unauth_401(client):
    resp = await client.post("/api/v1/billing/checkout-session", json=_VALID_BODY)

    assert resp.status_code == 401, (
        f"expected 401 (require_current_user dep); got {resp.status_code}. "
        f"If 404, uvicorn pid is stale — run scripts/restart-backend.sh. Body: {resp.text}"
    )


@pytest.mark.integration
async def test_checkout_session_invalid_plan_400(authed_client):
    client, _user, _token = authed_client

    resp = await client.post(
        "/api/v1/billing/checkout-session",
        json={
            "plan": "enterprise",
            "success_url": "https://localhost/ok",
            "cancel_url": "https://localhost/no",
        },
    )

    assert resp.status_code == 400, resp.text
    assert "unknown plan" in resp.text.lower()
