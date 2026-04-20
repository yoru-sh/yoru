"""Features router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_token, require_admin
from apps.api.api.models.subscription.feature_models import (
    FeatureCreate,
    FeatureResponse,
    FeatureUpdate,
)
from apps.api.api.services.subscription.feature_service import FeatureService


class FeaturesRouter:
    """Router for feature endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="FeaturesRouter")
        self.router = APIRouter(prefix="/features", tags=["features"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up feature routes."""
        # Public endpoints
        self.router.get(
            "",
            response_model=list[FeatureResponse],
            status_code=status.HTTP_200_OK,
            summary="List all features",
        )(self.list_features)

        self.router.get(
            "/{feature_id}",
            response_model=FeatureResponse,
            status_code=status.HTTP_200_OK,
            summary="Get feature details",
        )(self.get_feature)

        # Admin endpoints
        self.router.post(
            "/admin/features",
            response_model=FeatureResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create a new feature (admin)",
        )(self.create_feature)

        self.router.patch(
            "/admin/features/{feature_id}",
            response_model=FeatureResponse,
            status_code=status.HTTP_200_OK,
            summary="Update a feature (admin)",
        )(self.update_feature)

        self.router.delete(
            "/admin/features/{feature_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a feature (admin)",
        )(self.delete_feature)

    async def list_features(
        self,
        request: Request,
        correlation_id: str = Depends(get_correlation_id),
    ):
        """List all features."""
        service = FeatureService()
        return await service.list_features(correlation_id)

    async def get_feature(
        self,
        feature_id: UUID,
        request: Request,
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Get feature details."""
        service = FeatureService()
        return await service.get_feature(feature_id, correlation_id)

    async def create_feature(
        self,
        data: FeatureCreate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Create a new feature (admin only)."""
        service = FeatureService(access_token=token)
        return await service.create_feature(data, correlation_id)

    async def update_feature(
        self,
        feature_id: UUID,
        data: FeatureUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Update a feature (admin only)."""
        service = FeatureService(access_token=token)
        return await service.update_feature(
            feature_id, data, correlation_id
        )

    async def delete_feature(
        self,
        feature_id: UUID,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Delete a feature (admin only)."""
        service = FeatureService(access_token=token)
        await service.delete_feature(feature_id, correlation_id)
        return None
