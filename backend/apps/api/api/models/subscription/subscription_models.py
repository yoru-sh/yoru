"""Subscription models for subscription system."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionStatus(str, Enum):
    """Subscription status options."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING = "pending"


class SubscriptionBase(BaseModel):
    """Base subscription model."""

    plan_id: UUID
    promo_code: str | None = None
    org_id: UUID | None = Field(
        None,
        description="Organization ID for org-level billing. If not provided, uses user's default org.",
    )


class SubscriptionCreate(SubscriptionBase):
    """Model for creating a new subscription."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "plan_id": "0c198eb3-a164-452e-8f81-aef70fea6116",
                    "promo_code": "LAUNCH50",
                    "org_id": "550e8400-e29b-41d4-a716-446655440000",
                }
            ]
        }
    )


class SubscriptionUpdate(BaseModel):
    """Model for updating an existing subscription."""

    status: SubscriptionStatus | None = None


class SubscriptionResponse(BaseModel):
    """Subscription response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = Field(
        None, description="User ID (legacy, for backward compatibility)"
    )
    org_id: UUID | None = Field(
        None, description="Organization ID for org-level billing"
    )
    plan_id: UUID
    plan_name: str
    status: SubscriptionStatus
    start_date: datetime
    end_date: datetime | None
    created_at: datetime
    updated_at: datetime
    features: dict[str, Any]
    # Set once the user completes a Stripe Checkout. When NULL, the
    # Customer Portal isn't reachable — the UI should hide the "Manage"
    # button and the /billing/portal-session endpoint returns 404.
    stripe_customer_id: str | None = None
