"""Promo code router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_token, require_admin, require_auth
from apps.api.api.models.subscription.promo_models import (
    PromoCodeCreate,
    PromoCodeResponse,
    PromoCodeUpdate,
    PromoValidateRequest,
    PromoValidateResponse,
)
from apps.api.api.services.subscription.promo_service import PromoService


class PromoRouter:
    """Router for promo code endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="PromoRouter")
        self.router = APIRouter(prefix="/promo", tags=["promo"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up promo code routes."""
        # Public endpoints
        self.router.post(
            "/validate",
            response_model=PromoValidateResponse,
            status_code=status.HTTP_200_OK,
            summary="Validate a promo code",
        )(self.validate_promo_code)

        # Admin endpoints
        self.router.get(
            "/admin/promo",
            response_model=list[PromoCodeResponse],
            status_code=status.HTTP_200_OK,
            summary="List all promo codes (admin)",
        )(self.list_promo_codes)

        self.router.post(
            "/admin/promo",
            response_model=PromoCodeResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create a new promo code (admin)",
        )(self.create_promo_code)

        self.router.patch(
            "/admin/promo/{promo_id}",
            response_model=PromoCodeResponse,
            status_code=status.HTTP_200_OK,
            summary="Update a promo code (admin)",
        )(self.update_promo_code)

    async def validate_promo_code(
        self,
        data: PromoValidateRequest,
        request: Request,
        user_id: UUID = Depends(require_auth),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Validate a promo code."""
        service = PromoService(access_token=token)
        return await service.validate_promo_code(
            data, user_id, correlation_id
        )

    async def list_promo_codes(
        self,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """List all promo codes (admin only)."""
        service = PromoService(access_token=token)
        return await service.list_promo_codes(
            active_only=False, correlation_id=correlation_id
        )

    async def create_promo_code(
        self,
        data: PromoCodeCreate,
        request: Request,
        user_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Create a new promo code (admin only)."""
        service = PromoService(access_token=token)
        return await service.create_promo_code(data, user_id, correlation_id)

    async def update_promo_code(
        self,
        promo_id: UUID,
        data: PromoCodeUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Update a promo code (admin only)."""
        service = PromoService(access_token=token)
        return await service.update_promo_code(
            promo_id, data, correlation_id
        )
