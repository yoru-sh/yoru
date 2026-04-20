"""Plan models for subscription system."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BillingPeriod(str, Enum):
    """Billing period options."""

    MONTHLY = "monthly"
    ANNUAL = "annual"
    ONE_TIME = "one_time"


class PlanBase(BaseModel):
    """Base plan model."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(..., ge=0)
    billing_period: BillingPeriod
    is_active: bool = True
    is_custom: bool = False


class PlanCreate(PlanBase):
    """Model for creating a new plan."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Professional Plan",
                    "description": "Perfect for growing teams and businesses",
                    "price": 49.99,
                    "billing_period": "monthly",
                    "is_active": True,
                    "is_custom": False,
                    "features": ["550e8400-e29b-41d4-a716-446655440001"],
                }
            ]
        }
    )

    features: list[UUID] = Field(default=[], description="Feature IDs to attach")


class PlanUpdate(BaseModel):
    """Model for updating an existing plan."""

    name: str | None = Field(None, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(None, ge=0)
    billing_period: BillingPeriod | None = None
    is_active: bool | None = None


class FeatureWithValue(BaseModel):
    """Feature with its value in a plan."""

    id: UUID
    key: str
    name: str
    type: str
    value: dict | bool | int | str


class PlanResponse(PlanBase):
    """Plan response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    features: list[FeatureWithValue] = []


class FeatureValueUpdate(BaseModel):
    """Model for updating feature value in a plan."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"value": True},
                {"value": {"limit": 10000, "used": 0}},
            ]
        }
    )

    value: dict | bool | int | str = Field(
        ..., description="New value for the feature"
    )
