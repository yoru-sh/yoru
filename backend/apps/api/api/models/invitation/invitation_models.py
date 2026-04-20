"""Invitation models for invitation system."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InvitationStatus(str, Enum):
    """Invitation status options."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InvitationBase(BaseModel):
    """Base invitation model."""

    email: EmailStr = Field(..., description="Email address of the invitee")


class InvitationCreate(InvitationBase):
    """Model for creating a new invitation."""

    message: str | None = Field(
        None, max_length=500, description="Optional custom message"
    )


class InvitationAccept(BaseModel):
    """Model for accepting an invitation."""

    password: str = Field(..., min_length=8, description="Password for the new account")
    first_name: str | None = Field(None, description="Optional first name")
    last_name: str | None = Field(None, description="Optional last name")


class InvitationResponse(BaseModel):
    """Invitation response model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    status: InvitationStatus
    invited_by: UUID
    invited_by_email: str | None = None  # Enriched by service
    message: str | None = None
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InvitationPublicResponse(BaseModel):
    """Public invitation info (before accepting)."""

    email: str
    invited_by_email: str
    message: str | None = None
    expires_at: datetime
    is_expired: bool


class InvitationListResponse(BaseModel):
    """Response for list of invitations."""

    items: list[InvitationResponse]
    total: int
    pending_count: int
    accepted_count: int
    expired_count: int
