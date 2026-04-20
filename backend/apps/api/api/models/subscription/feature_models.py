"""Feature models for subscription system."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeatureType(str, Enum):
    """Feature type options."""

    FLAG = "flag"
    QUOTA = "quota"


class FeatureBase(BaseModel):
    """Base feature model."""

    key: str = Field(
        ..., min_length=1, max_length=100, description="Unique key (ex: ai_analysis)"
    )
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    type: FeatureType
    default_value: dict | bool | int | str = Field(
        ..., description="Default value for this feature"
    )


class FeatureCreate(FeatureBase):
    """Model for creating a new feature."""

    pass


class FeatureUpdate(BaseModel):
    """Model for updating an existing feature."""

    name: str | None = None
    description: str | None = None
    default_value: dict | bool | int | str | None = None


class FeatureResponse(FeatureBase):
    """Feature response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
