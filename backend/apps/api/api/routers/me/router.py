"""Me router for current user operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import get_correlation_id, get_current_user_id, get_current_user_token
from apps.api.api.models.user.user_models import UserResponse, UserUpdate
from apps.api.api.models.subscription.subscription_models import SubscriptionResponse
from apps.api.api.models.subscription.grant_models import GrantResponse
from apps.api.api.models.group.group_models import (
    UserGroupResponse,
    GroupFeatureResponse,
)
from apps.api.api.services.user.user_service import UserService
from apps.api.api.services.subscription.subscription_service import SubscriptionService
from apps.api.api.services.subscription.grant_service import GrantService
from apps.api.api.services.group.group_service import UserGroupService


class MeRouter:
    """Router for current user endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="MeRouter")
        self.router = APIRouter(prefix="/me", tags=["me"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used anymore as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up me routes."""
        self.router.get(
            "",
            response_model=UserResponse,
            status_code=200,
            summary="Get current user profile",
        )(self.get_me)

        self.router.patch(
            "",
            response_model=UserResponse,
            status_code=200,
            summary="Update current user profile",
        )(self.update_me)

        self.router.get(
            "/subscription",
            response_model=SubscriptionResponse | None,
            status_code=200,
            summary="Get current user's subscription",
        )(self.get_my_subscription)

        self.router.get(
            "/grants",
            response_model=list[GrantResponse],
            status_code=200,
            summary="Get current user's grants",
        )(self.get_my_grants)

        self.router.get(
            "/groups",
            response_model=list[UserGroupResponse],
            status_code=200,
            summary="Get current user's groups",
        )(self.get_my_groups)

        self.router.get(
            "/groups/features",
            response_model=list[GroupFeatureResponse],
            status_code=200,
            summary="Get features accessible via user's groups",
        )(self.get_my_group_features)

    async def get_me(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserResponse:
        """
        Get the current user's profile.

        Requires authentication via Bearer token.
        """
        user_service = UserService(access_token=token)
        return await user_service.get_by_id(user_id, correlation_id)

    async def update_me(
        self,
        request: Request,
        data: UserUpdate,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserResponse:
        """
        Update the current user's profile.

        Only provided fields will be updated.
        Requires authentication via Bearer token.
        """
        user_service = UserService(access_token=token)
        return await user_service.update(user_id, data, correlation_id)

    async def get_my_subscription(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        correlation_id: str = Depends(get_correlation_id),
    ) -> SubscriptionResponse | None:
        """
        Get the current user's active subscription.

        Returns None if user has no active subscription.
        Requires authentication via Bearer token.
        """
        subscription_service = SubscriptionService()
        return await subscription_service.get_user_active_subscription(
            user_id, correlation_id
        )

    async def get_my_grants(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[GrantResponse]:
        """
        Get the current user's active grants.

        Returns list of grants that override subscription features.
        Requires authentication via Bearer token.
        """
        grant_service = GrantService()
        return await grant_service.get_active_user_grants(user_id, correlation_id)

    async def get_my_groups(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[UserGroupResponse]:
        """
        Get all groups the current user belongs to.

        Returns list of active groups with member counts.
        Requires authentication via Bearer token.
        """
        group_service = UserGroupService(access_token=token)
        return await group_service.get_user_groups(user_id, correlation_id)

    async def get_my_group_features(
        self,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[GroupFeatureResponse]:
        """
        Get all features accessible to the current user via their group memberships.

        Returns list of features with their values, organized by group.
        Requires authentication via Bearer token.
        """
        group_service = UserGroupService(access_token=token)
        return await group_service.get_user_features_via_groups(user_id, correlation_id)
