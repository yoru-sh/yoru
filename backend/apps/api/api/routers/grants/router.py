"""Grants router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_token, require_admin, require_auth
from apps.api.api.models.subscription.grant_models import (
    GrantCreate,
    GrantResponse,
    GrantUpdate,
)
from apps.api.api.services.subscription.grant_service import GrantService


class GrantsRouter:
    """Router for grant endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="GrantsRouter")
        self.router = APIRouter(prefix="/grants", tags=["grants"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up grant routes."""
        # Admin endpoints
        self.router.get(
            "/admin/grants",
            response_model=list[GrantResponse],
            status_code=status.HTTP_200_OK,
            summary="List all grants (admin)",
        )(self.list_all_grants)

        self.router.get(
            "/admin/users/{user_id}/grants",
            response_model=list[GrantResponse],
            status_code=status.HTTP_200_OK,
            summary="List grants for a specific user (admin)",
        )(self.list_user_grants)

        self.router.post(
            "/admin/grants",
            response_model=GrantResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create a new grant (admin)",
        )(self.create_grant)

        self.router.patch(
            "/admin/grants/{grant_id}",
            response_model=GrantResponse,
            status_code=status.HTTP_200_OK,
            summary="Update a grant (admin)",
        )(self.update_grant)

        self.router.delete(
            "/admin/grants/{grant_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a grant (admin)",
        )(self.delete_grant)

    async def list_all_grants(
        self,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """List all grants (admin only)."""
        service = GrantService(access_token=token)
        return await service.list_all_grants(correlation_id)

    async def list_user_grants(
        self,
        user_id: UUID,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """List grants for a specific user (admin only)."""
        service = GrantService(access_token=token)
        return await service.list_user_grants(user_id, correlation_id)

    async def create_grant(
        self,
        data: GrantCreate,
        request: Request,
        granted_by: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Create a new grant (admin only)."""
        service = GrantService(access_token=token)
        return await service.create_grant(data, granted_by, correlation_id)

    async def update_grant(
        self,
        grant_id: UUID,
        data: GrantUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Update a grant (admin only)."""
        service = GrantService(access_token=token)
        return await service.update_grant(grant_id, data, correlation_id)

    async def delete_grant(
        self,
        grant_id: UUID,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Delete a grant (admin only)."""
        service = GrantService(access_token=token)
        await service.delete_grant(grant_id, correlation_id)
        return None
