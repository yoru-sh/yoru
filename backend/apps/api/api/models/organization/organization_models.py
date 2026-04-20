"""Organization models for multi-tenancy system."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationType(str, Enum):
    """Organization type enum."""

    PERSONAL = "personal"
    TEAM = "team"


class OrganizationRole(str, Enum):
    """Organization member role enum."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


# =============================================
# Organization Models
# =============================================


class OrganizationBase(BaseModel):
    """Base organization model with common fields."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Organization name"
    )
    avatar_url: str | None = Field(None, description="Organization avatar URL")
    settings: dict = Field(default_factory=dict, description="Organization settings")


class OrganizationCreate(BaseModel):
    """Model for creating a new organization."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Organization name"
    )
    type: OrganizationType = Field(
        OrganizationType.TEAM, description="Organization type"
    )
    avatar_url: str | None = Field(None, description="Organization avatar URL")
    settings: dict = Field(default_factory=dict, description="Organization settings")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate organization name."""
        return v.strip()


class OrganizationUpdate(BaseModel):
    """Model for updating an existing organization."""

    name: str | None = Field(None, min_length=1, max_length=100)
    avatar_url: str | None = None
    settings: dict | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate organization name."""
        if v is not None:
            return v.strip()
        return v


class OrganizationResponse(BaseModel):
    """Organization response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    type: OrganizationType
    owner_id: UUID
    avatar_url: str | None
    settings: dict
    created_at: datetime
    updated_at: datetime
    member_count: int = Field(0, description="Number of members in the organization")
    current_user_role: OrganizationRole | None = Field(
        None, description="Current user's role in this organization"
    )


class OrganizationListResponse(BaseModel):
    """List response for organizations with pagination."""

    model_config = ConfigDict(from_attributes=True)

    items: list[OrganizationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Organization Member Models
# =============================================


class OrganizationMemberAdd(BaseModel):
    """Model for adding a user to an organization directly."""

    user_id: UUID = Field(..., description="User ID to add to the organization")
    role: OrganizationRole = Field(
        OrganizationRole.MEMBER, description="Role to assign"
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: OrganizationRole) -> OrganizationRole:
        """Validate that owner role cannot be directly assigned."""
        if v == OrganizationRole.OWNER:
            msg = "Cannot directly assign owner role"
            raise ValueError(msg)
        return v


class OrganizationMemberUpdate(BaseModel):
    """Model for updating member role."""

    role: OrganizationRole = Field(..., description="New role for the member")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: OrganizationRole) -> OrganizationRole:
        """Validate that owner role cannot be assigned via update."""
        if v == OrganizationRole.OWNER:
            msg = "Cannot assign owner role via update"
            raise ValueError(msg)
        return v


class OrganizationMemberResponse(BaseModel):
    """Organization member response model."""

    model_config = ConfigDict(from_attributes=True)

    org_id: UUID
    user_id: UUID
    role: OrganizationRole
    joined_at: datetime
    invited_by: UUID | None
    user_email: str | None = Field(None, description="User email for display")
    user_name: str | None = Field(None, description="User name for display")


# =============================================
# Organization Invitation Models
# =============================================


class OrganizationInvitationCreate(BaseModel):
    """Model for creating an organization invitation."""

    email: str = Field(..., description="Email address to invite")
    role: OrganizationRole = Field(
        OrganizationRole.MEMBER, description="Role to assign on acceptance"
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.lower().strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: OrganizationRole) -> OrganizationRole:
        """Validate that owner role cannot be invited."""
        if v == OrganizationRole.OWNER:
            msg = "Cannot invite with owner role"
            raise ValueError(msg)
        return v


class OrganizationInvitationResponse(BaseModel):
    """Organization invitation response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    email: str
    role: OrganizationRole
    token: str | None = Field(
        None, description="Token only visible to admins/owners or recipient"
    )
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    org_name: str | None = Field(None, description="Organization name for display")
    inviter_name: str | None = Field(None, description="Inviter name for display")


class OrganizationInvitationPublicResponse(BaseModel):
    """Public invitation info (for acceptance page)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_name: str
    org_avatar_url: str | None
    email: str
    role: OrganizationRole
    inviter_name: str | None
    expires_at: datetime
    is_expired: bool = Field(False, description="Whether invitation has expired")


# =============================================
# Detailed Models
# =============================================


class OrganizationDetailResponse(OrganizationResponse):
    """Detailed organization response with members."""

    model_config = ConfigDict(from_attributes=True)

    members: list[OrganizationMemberResponse] = Field(default_factory=list)
    pending_invitations: list[OrganizationInvitationResponse] = Field(
        default_factory=list
    )
