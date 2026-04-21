"""Wave-54 V4-1(a) — quota paywall on POST /api/v1/sessions/events.

Spec: vault/USER_STORIES-v4.md US-V4-1 AC #1. When a free org has already
created `plan.session_cap` sessions in the current UTC calendar month, the
next ingest POST returns 402 with body
`{"upgrade_required": "team", "checkout_url": "https://checkout.polar.sh/..."}`.

Scenarios:
  - free org @ 100 sessions → 402 with exact body shape
  - team org @ 100 sessions → 200 (cap is 2000, still well under)
  - free org @ 100 sessions, then upgrade to team → same batch succeeds
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession

from apps.api.api.routers.billing import checkout as checkout_module
from apps.api.api.routers.billing.checkout import _resolve_org_id
from apps.api.api.routers.billing.models import Org
from apps.api.api.routers.receipt.models import Session as SessionRow

_POLAR_URL = "https://checkout.polar.sh/session/test-402-paywall"
_USER = "alice@example.com"


@pytest.fixture()
def mock_polar(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Swap the module-level Polar client so `.checkouts.create(...).url` is deterministic."""
    client = MagicMock()
    client.checkouts.create.return_value = MagicMock(url=_POLAR_URL, id="ch_test")
    monkeypatch.setattr(checkout_module, "_polar_client", client)
    return client


def _seed_sessions(db: DBSession, user: str, n: int) -> None:
    """Create `n` sessions for `user` dated safely inside the current UTC month.

    Each session is spaced one second apart starting at the month-start + 1h
    so the `started_at >= month_start` filter always includes them even if
    the suite runs at exactly 00:00 UTC on the 1st.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    base = now.replace(day=1, hour=1, minute=0, second=0, microsecond=0)
    for i in range(n):
        db.add(
            SessionRow(
                id=f"{user}-seed-{i}",
                user=user,
                started_at=base + timedelta(seconds=i),
            )
        )
    db.commit()


def _upsert_org(db: DBSession, user: str, plan: str) -> str:
    org_id = str(_resolve_org_id(user))
    existing = db.get(Org, org_id)
    if existing is None:
        db.add(Org(id=org_id, plan=plan))
    else:
        existing.plan = plan
        db.add(existing)
    db.commit()
    return org_id


def _batch(session_id: str, user: str) -> dict[str, Any]:
    return {
        "events": [
            {
                "session_id": session_id,
                "user": user,
                "kind": "tool_use",
                "tool": "Edit",
                "content": "noop",
            }
        ]
    }


def test_free_org_at_cap_returns_402_with_exact_body(
    client: TestClient, db_session: DBSession, mock_polar: MagicMock
) -> None:
    _upsert_org(db_session, _USER, plan="free")
    _seed_sessions(db_session, _USER, 100)

    resp = client.post("/api/v1/sessions/events", json=_batch("new-over-cap", _USER))

    assert resp.status_code == 402, resp.text
    body = resp.json()
    # EXACT shape — frontend banner + CLI stderr both parse by these two keys.
    assert set(body.keys()) == {"upgrade_required", "checkout_url"}
    assert body["upgrade_required"] == "team"
    assert body["checkout_url"] == _POLAR_URL
    assert body["checkout_url"].startswith("https://checkout.polar.sh/")

    # 402 is a pre-write gate: no new session row is created.
    assert db_session.get(SessionRow, "new-over-cap") is None


def test_team_org_at_100_sessions_returns_202(
    client: TestClient, db_session: DBSession, mock_polar: MagicMock
) -> None:
    _upsert_org(db_session, _USER, plan="team")
    _seed_sessions(db_session, _USER, 100)

    resp = client.post("/api/v1/sessions/events", json=_batch("team-ok", _USER))

    assert resp.status_code == 202, resp.text
    assert db_session.get(SessionRow, "team-ok") is not None
    # No paywall call on the happy path — saves an SDK round-trip per ingest.
    mock_polar.checkouts.create.assert_not_called()


def test_free_org_after_upgrade_same_batch_succeeds(
    client: TestClient, db_session: DBSession, mock_polar: MagicMock
) -> None:
    _upsert_org(db_session, _USER, plan="free")
    _seed_sessions(db_session, _USER, 100)

    batch = _batch("idempotent-batch", _USER)
    blocked = client.post("/api/v1/sessions/events", json=batch)
    assert blocked.status_code == 402

    _upsert_org(db_session, _USER, plan="team")  # simulate Polar webhook flipping the plan
    db_session.expire_all()  # drop cached Org so the router re-reads `plan`

    retried = client.post("/api/v1/sessions/events", json=batch)
    assert retried.status_code == 202, retried.text
    assert db_session.get(SessionRow, "idempotent-batch") is not None
