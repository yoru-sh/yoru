"""Billing SQLModel tables — Polar webhook processing (US-16, wave-20-C C1).

- `Org` is a STUB until the real Org table lands with US-18 invite work.
- `BillingEvent` is the idempotency ledger — PK on provider event id so
  replayed events short-circuit via `db.get(BillingEvent, event_id)`.

Contract: vault/BACKEND-API-V1.md §4.2 + wave-20-C C1 task brief.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow_naive() -> datetime:
    # SQLite strips tzinfo on readback — keep everything naive UTC to avoid
    # aware/naive comparison errors (receipt.deps._naive_utc_now pattern).
    return datetime.now(timezone.utc).replace(tzinfo=None)


# TODO: real Org table model lives with US-18 invite work.
class Org(SQLModel, table=True):
    __tablename__ = "orgs"

    id: str = Field(primary_key=True)
    plan: str = Field(default="free", index=True)
    seat_count: int = Field(default=1)
    plan_downgrades_at: Optional[datetime] = Field(default=None)


class BillingEvent(SQLModel, table=True):
    __tablename__ = "billing_events"

    event_id: str = Field(primary_key=True)
    processed_at: datetime = Field(default_factory=_utcnow_naive)
    org_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)
