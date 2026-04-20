"""Group models for RBAC system."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class UserGroupBase(BaseModel):
    """Base user group model with common fields."""

    name: str = Field(..., min_length=1, max_length=100, description="Group name")
    description: str | None = Field(None, description="Group description")
    is_active: bool = Field(True, description="Whether the group is active")


class UserGroupCreate(UserGroupBase):
    """Model for creating a new user group."""

    pass


class UserGroupUpdate(BaseModel):
    """Model for updating an existing user group."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class UserGroupResponse(UserGroupBase):
    """User group response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    member_count: int = Field(0, description="Number of members in the group")


# =============================================
# Group Member Models
# =============================================


class GroupMemberAdd(BaseModel):
    """Model for adding a user to a group."""

    user_id: UUID = Field(..., description="User ID to add to the group")


class GroupMemberResponse(BaseModel):
    """Group member response model."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    group_id: UUID
    added_by: UUID | None
    added_at: datetime
    user_email: str | None = Field(None, description="User email for display")
    user_name: str | None = Field(None, description="User name for display")


# =============================================
# Group Feature Models
# =============================================


class GroupFeatureAssign(BaseModel):
    """Model for assigning a feature to a group."""

    feature_id: UUID = Field(..., description="Feature ID to assign")
    value: dict | bool | int | str = Field(
        ...,
        description="Feature value (bool for flags, int for quotas, dict for config)",
    )


class GroupFeatureResponse(BaseModel):
    """Group feature response model."""

    model_config = ConfigDict(from_attributes=True)

    group_id: UUID
    feature_id: UUID
    feature_key: str = Field(..., description="Feature key for reference")
    feature_name: str = Field(..., description="Feature name for display")
    value: dict | bool | int | str
    created_at: datetime


# =============================================
# Detailed Models (defined after dependencies)
# =============================================


class UserGroupDetailResponse(UserGroupResponse):
    """Detailed user group response with members and features."""

    model_config = ConfigDict(from_attributes=True)

    members: list[GroupMemberResponse] = Field(default_factory=list)
    features: list[GroupFeatureResponse] = Field(default_factory=list)


class UserGroupListResponse(BaseModel):
    """List response for user groups with pagination."""

    model_config = ConfigDict(from_attributes=True)

    items: list[UserGroupResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
