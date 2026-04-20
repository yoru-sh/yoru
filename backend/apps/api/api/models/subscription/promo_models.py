"""Promo code models for subscription system."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DiscountType(str, Enum):
    """Discount type options."""

    PERCENTAGE = "percentage"
    FIXED = "fixed"


class PromoCodeBase(BaseModel):
    """Base promo code model."""

    code: str = Field(..., min_length=3, max_length=50)
    type: DiscountType
    value: Decimal = Field(..., gt=0)
    max_uses: int | None = Field(None, ge=1)
    expires_at: datetime | None = None
    conditions: dict[str, Any] | None = None
    is_active: bool = True


class PromoCodeCreate(PromoCodeBase):
    """Model for creating a new promo code."""

    pass


class PromoCodeUpdate(BaseModel):
    """Model for updating an existing promo code."""

    is_active: bool | None = None
    max_uses: int | None = None
    expires_at: datetime | None = None


class PromoCodeResponse(PromoCodeBase):
    """Promo code response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    current_uses: int
    created_by: UUID | None
    created_at: datetime


class PromoValidateRequest(BaseModel):
    """Request model for validating a promo code."""

    code: str
    plan_id: UUID


class PromoValidateResponse(BaseModel):
    """Response model for promo code validation."""

    valid: bool
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None
    final_price: Decimal | None = None
    message: str
