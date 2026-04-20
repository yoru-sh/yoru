"""Admin router for broadcasting notifications."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_token, require_admin
from apps.api.api.models.notification.notification_models import NotificationBroadcast
from apps.api.api.services.notification.notification_service import NotificationService


class NotificationAdminRouter:
    """Router admin pour broadcast de notifications système."""

    def __init__(self):
        self.logger = LoggingController(app_name="NotificationAdminRouter")
        self.router = APIRouter(prefix="/admin/notifications", tags=["admin"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up admin notification routes."""
        self.router.post(
            "/broadcast",
            status_code=status.HTTP_201_CREATED,
            summary="Broadcast system notification (admin only)",
        )(self.broadcast_notification)

    async def broadcast_notification(
        self,
        data: NotificationBroadcast,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Broadcast notification système (admin only).

        Envoie une notification à tous les utilisateurs ou à un groupe spécifique.

        **Requires admin role.**

        **Example Request (broadcast to all):**
        ```bash
        curl -X POST http://localhost:8000/api/v1/admin/notifications/broadcast \\
          -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \\
          -H "Content-Type: application/json" \\
          -d '{
            "title": "System Maintenance",
            "message": "The system will be under maintenance on Sunday 2-4AM UTC.",
            "type": "warning",
            "action_url": "/status"
          }'
        ```

        **Example Request (targeted users):**
        ```bash
        curl -X POST http://localhost:8000/api/v1/admin/notifications/broadcast \\
          -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \\
          -H "Content-Type: application/json" \\
          -d '{
            "title": "Premium Feature Available",
            "message": "You now have access to premium features!",
            "type": "success",
            "target_user_ids": ["550e8400-e29b-41d4-a716-446655440000"]
          }'
        ```

        **Parameters:**
        - **title**: Titre de la notification (max 255 chars)
        - **message**: Message de la notification (max 1000 chars)
        - **type**: Type (info, success, warning, error)
        - **action_url**: Optional URL for action button
        - **target_user_ids**: Optional list of user IDs (omit for broadcast to all)

        **Returns:**
        - **recipients_count**: Number of notifications created
        """
        service = NotificationService(access_token=token)
        count = await service.broadcast_notification(
            admin_id=admin_id,
            title=data.title,
            message=data.message,
            type=data.type,
            action_url=data.action_url,
            target_user_ids=data.target_user_ids,
            correlation_id=correlation_id,
        )

        return {
            "message": f"Notification broadcast to {count} users",
            "recipients_count": count,
        }
