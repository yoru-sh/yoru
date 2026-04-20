"""Notifications router for user endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_id, get_current_user_token
from apps.api.api.models.notification.notification_models import (
    NotificationListResponse,
    NotificationResponse,
)
from apps.api.api.services.notification.notification_service import NotificationService


class NotificationRouter:
    """Router for user notification endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="NotificationRouter")
        self.router = APIRouter(prefix="/me/notifications", tags=["notifications"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up notification routes."""
        self.router.get(
            "",
            response_model=NotificationListResponse,
            status_code=status.HTTP_200_OK,
            summary="List user notifications with pagination",
        )(self.list_notifications)

        self.router.get(
            "/unread/count",
            status_code=status.HTTP_200_OK,
            summary="Get unread notification count for bell icon",
        )(self.get_unread_count)

        self.router.patch(
            "/{notification_id}/read",
            response_model=NotificationResponse,
            status_code=status.HTTP_200_OK,
            summary="Mark a notification as read",
        )(self.mark_as_read)

        self.router.patch(
            "/read-all",
            status_code=status.HTTP_200_OK,
            summary="Mark all notifications as read",
        )(self.mark_all_as_read)

        self.router.delete(
            "/{notification_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a notification",
        )(self.delete_notification)

    async def list_notifications(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        is_read: bool | None = Query(None, description="Filter by read status (true/false/null for all)"),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        page_size: int = Query(50, ge=1, le=200, description="Items per page"),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Liste paginée des notifications de l'utilisateur.

        - **is_read**: Optionnel, filtrer par statut lu/non-lu
        - **page**: Numéro de page (default: 1)
        - **page_size**: Items par page (default: 50, max: 200)

        Returns pagination metadata including unread_count for bell icon.
        """
        service = NotificationService(access_token=token)
        return await service.get_user_notifications(
            user_id, is_read, page, page_size, correlation_id
        )

    async def get_unread_count(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Nombre de notifications non lues (pour bell icon).

        Returns a simple count of unread notifications for the authenticated user.
        """
        service = NotificationService(access_token=token)
        count = await service.get_unread_count(user_id, correlation_id)
        return {"unread_count": count}

    async def mark_as_read(
        self,
        notification_id: UUID,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Marquer une notification comme lue.

        - **notification_id**: UUID de la notification

        Sets is_read=true and read_at=now() for the specified notification.
        """
        service = NotificationService(access_token=token)
        return await service.mark_as_read(
            notification_id, user_id, correlation_id
        )

    async def mark_all_as_read(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Marquer toutes les notifications comme lues.

        Sets is_read=true for all unread notifications of the authenticated user.
        Returns the count of updated notifications.
        """
        service = NotificationService(access_token=token)
        count = await service.mark_all_as_read(user_id, correlation_id)
        return {"updated_count": count}

    async def delete_notification(
        self,
        notification_id: UUID,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Supprimer une notification.

        - **notification_id**: UUID de la notification

        Permanently deletes the notification if it belongs to the authenticated user.
        """
        service = NotificationService(access_token=token)
        await service.delete_notification(
            notification_id, user_id, correlation_id
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
