"""Webhook subscription SQLModel — Wave-34 US-23 outbound webhooks (W1).

Per-user (email-scoped) outbound webhook config. v0 carries no `org_id`:
the org-model is postponed to v1.5; US-23 ships standalone with the same
`user` scoping convention as `Session.user` and `HookToken.user`.

Naive UTC datetimes — SQLite drops tzinfo (self-learning §SQLite-naive-UTC).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_id() -> str:
    return uuid.uuid4().hex


class WebhookSubscription(SQLModel, table=True):
    __tablename__ = "webhook_subscriptions"

    id: str = Field(primary_key=True, default_factory=_new_id)
    user: str = Field(index=True)
    url: str
    secret: str
    events_filter: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_naive_utcnow)
    last_delivery_at: Optional[datetime] = None
    last_status: Optional[int] = None
