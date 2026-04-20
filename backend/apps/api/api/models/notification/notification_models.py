"""
Models Pydantic pour le système de notifications in-app.

Respect des règles :
- api.responses.mdc : BaseModel + from_attributes + UUID
- python.typing.mdc : Type hints complets + | None pour optionnels
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationType(str, Enum):
    """Type de notification (info, success, warning, error)."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationBase(BaseModel):
    """Champs communs base."""

    title: str = Field(
        ..., min_length=1, max_length=255, description="Titre de la notification"
    )
    message: str = Field(
        ..., min_length=1, max_length=1000, description="Message de la notification"
    )
    type: NotificationType = Field(
        default=NotificationType.INFO, description="Type de notification"
    )
    action_url: str | None = Field(None, description="URL d'action optionnelle")
    metadata: dict | None = Field(default_factory=dict, description="Données additionnelles JSON")


class NotificationCreate(NotificationBase):
    """Model pour création de notification."""

    user_id: UUID = Field(..., description="ID de l'utilisateur destinataire")


class NotificationBroadcast(NotificationBase):
    """Model pour broadcast admin (notification système)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "System Maintenance",
                    "message": "The system will be under maintenance on Sunday from 2AM to 4AM UTC.",
                    "type": "warning",
                    "action_url": "/status",
                    "metadata": {"maintenance_window": "2024-02-20T02:00:00Z"},
                }
            ]
        }
    )

    # broadcast_by will be set from the admin_id in the service
    target_user_ids: list[UUID] | None = Field(
        None,
        description="Liste IDs users spécifiques (sinon tous)",
        examples=[["550e8400-e29b-41d4-a716-446655440000"]]
    )


class NotificationResponse(NotificationBase):
    """Model de réponse avec tous les champs DB."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    is_read: bool
    read_at: datetime | None = None
    broadcast_by: UUID | None = Field(
        None, description="ID admin si notification système"
    )
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    """Liste paginée de notifications avec métadonnées."""

    items: list[NotificationResponse]
    total: int = Field(..., description="Nombre total de notifications")
    unread_count: int = Field(..., description="Nombre de notifications non lues")
    page: int = Field(..., ge=1, description="Page courante (1-indexed)")
    page_size: int = Field(..., ge=1, le=200, description="Items par page")
    total_pages: int = Field(..., description="Nombre total de pages")
    has_more: bool = Field(..., description="Y a-t-il une page suivante ?")
