"""Grant models for subscription system."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GrantBase(BaseModel):
    """Base grant model."""

    user_id: UUID
    feature_id: UUID
    value: dict | bool | int | str = Field(
        ..., description="Override value for feature"
    )
    reason: str | None = Field(
        None, max_length=500, description="Why this grant was given"
    )
    expires_at: datetime | None = None


class GrantCreate(GrantBase):
    """Model for creating a new grant."""

    pass


class GrantUpdate(BaseModel):
    """Model for updating an existing grant."""

    value: dict | bool | int | str | None = None
    reason: str | None = None
    expires_at: datetime | None = None


class GrantResponse(GrantBase):
    """Grant response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    granted_by: UUID | None
    created_at: datetime
    feature_key: str
    feature_name: str
