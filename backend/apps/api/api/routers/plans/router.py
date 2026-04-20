"""Plans router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_token, require_admin, require_auth
from apps.api.api.models.subscription.plan_models import (
    FeatureValueUpdate,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
)
from apps.api.api.services.subscription.plan_service import PlanService


class PlansRouter:
    """Router for plan endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="PlansRouter")
        self.router = APIRouter(prefix="/plans", tags=["plans"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up plan routes."""
        # Public endpoints
        self.router.get(
            "",
            response_model=list[PlanResponse],
            status_code=status.HTTP_200_OK,
            summary="List all active plans",
        )(self.list_plans)

        self.router.get(
            "/{plan_id}",
            response_model=PlanResponse,
            status_code=status.HTTP_200_OK,
            summary="Get plan details with features",
        )(self.get_plan)

        # Admin endpoints
        self.router.post(
            "/admin/plans",
            response_model=PlanResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create a new plan (admin)",
        )(self.create_plan)

        self.router.patch(
            "/admin/plans/{plan_id}",
            response_model=PlanResponse,
            status_code=status.HTTP_200_OK,
            summary="Update a plan (admin)",
        )(self.update_plan)

        self.router.delete(
            "/admin/plans/{plan_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a plan (admin)",
        )(self.delete_plan)

        self.router.post(
            "/admin/plans/{plan_id}/features/{feature_id}",
            status_code=status.HTTP_201_CREATED,
            summary="Add feature to plan (admin)",
        )(self.add_feature_to_plan)

        self.router.patch(
            "/admin/plans/{plan_id}/features/{feature_id}",
            status_code=status.HTTP_200_OK,
            summary="Update feature value in plan (admin)",
        )(self.update_plan_feature_value)

        self.router.delete(
            "/admin/plans/{plan_id}/features/{feature_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Remove feature from plan (admin)",
        )(self.remove_feature_from_plan)

    async def list_plans(
        self,
        request: Request,
        correlation_id: str = Depends(get_correlation_id),
    ):
        """List all active plans."""
        service = PlanService()
        return await service.list_plans(
            active_only=True, correlation_id=correlation_id
        )

    async def get_plan(
        self,
        plan_id: UUID,
        request: Request,
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Get plan details with features."""
        service = PlanService()
        return await service.get_plan_with_features(
            plan_id, correlation_id
        )

    async def create_plan(
        self,
        data: PlanCreate,
        request: Request,
        user_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Create a new plan (admin only)."""
        service = PlanService(access_token=token)
        return await service.create_plan(data, user_id, correlation_id)

    async def update_plan(
        self,
        plan_id: UUID,
        data: PlanUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Update a plan (admin only)."""
        service = PlanService(access_token=token)
        return await service.update_plan(plan_id, data, correlation_id)

    async def delete_plan(
        self,
        plan_id: UUID,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Delete a plan (admin only)."""
        service = PlanService(access_token=token)
        await service.delete_plan(plan_id, correlation_id)
        return None

    async def add_feature_to_plan(
        self,
        plan_id: UUID,
        feature_id: UUID,
        data: FeatureValueUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Add feature to plan (admin only)."""
        service = PlanService(access_token=token)
        await service.add_feature_to_plan(
            plan_id, feature_id, data.value, correlation_id
        )
        return {"message": "Feature added to plan successfully"}

    async def update_plan_feature_value(
        self,
        plan_id: UUID,
        feature_id: UUID,
        data: FeatureValueUpdate,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Update feature value in plan (admin only)."""
        service = PlanService(access_token=token)
        await service.update_plan_feature_value(
            plan_id, feature_id, data, correlation_id
        )
        return {"message": "Feature value updated successfully"}

    async def remove_feature_from_plan(
        self,
        plan_id: UUID,
        feature_id: UUID,
        request: Request,
        _: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """Remove feature from plan (admin only)."""
        service = PlanService(access_token=token)
        await service.remove_feature_from_plan(
            plan_id, feature_id, correlation_id
        )
        return None
