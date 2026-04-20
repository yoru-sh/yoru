"""Admin router for user groups management."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import (
    get_correlation_id,
    get_current_user_token,
    require_admin,
)
from apps.api.api.models.group.group_models import (
    GroupFeatureAssign,
    GroupFeatureResponse,
    GroupMemberAdd,
    GroupMemberResponse,
    UserGroupCreate,
    UserGroupDetailResponse,
    UserGroupListResponse,
    UserGroupResponse,
    UserGroupUpdate,
)
from apps.api.api.services.group.group_service import UserGroupService


class AdminGroupsRouter:
    """Router for admin user group management."""

    def __init__(self):
        self.logger = LoggingController(app_name="AdminGroupsRouter")
        self.router = APIRouter(prefix="/admin/groups", tags=["admin", "groups"])
        self._setup_routes()

    def initialize_services(self):
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self):
        """Set up admin group routes."""
        # Group CRUD
        self.router.get("", response_model=UserGroupListResponse)(self.list_groups)
        self.router.post(
            "",
            response_model=UserGroupResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.create_group)
        self.router.get("/{group_id}", response_model=UserGroupDetailResponse)(
            self.get_group
        )
        self.router.patch("/{group_id}", response_model=UserGroupResponse)(
            self.update_group
        )
        self.router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)(
            self.delete_group
        )

        # Member management
        self.router.get(
            "/{group_id}/members", response_model=list[GroupMemberResponse]
        )(self.list_members)
        self.router.post(
            "/{group_id}/members",
            response_model=GroupMemberResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.add_member)
        self.router.delete(
            "/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
        )(self.remove_member)

        # Feature management
        self.router.get(
            "/{group_id}/features", response_model=list[GroupFeatureResponse]
        )(self.list_features)
        self.router.post(
            "/{group_id}/features",
            response_model=GroupFeatureResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.assign_feature)
        self.router.delete(
            "/{group_id}/features/{feature_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )(self.revoke_feature)

    # =============================================
    # Group CRUD Endpoints
    # =============================================

    async def list_groups(
        self,
        request: Request,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=200, description="Items per page"),
        is_active: bool | None = Query(None, description="Filter by active status"),
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserGroupListResponse:
        """
        List all user groups with pagination (admin only).

        Returns paginated list of groups with member counts.

        **Parameters:**
        - **page**: Page number (default: 1)
        - **page_size**: Items per page (default: 50, max: 200)
        - **is_active**: Filter by active status (optional)

        **Returns:**
        - **items**: List of groups
        - **total**: Total number of groups
        - **page**: Current page number
        - **page_size**: Items per page
        - **total_pages**: Total number of pages
        """
        service = UserGroupService(access_token=token)
        return await service.list_groups(
            correlation_id=correlation_id,
            page=page,
            page_size=page_size,
            is_active=is_active,
        )

    async def create_group(
        self,
        data: UserGroupCreate,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserGroupResponse:
        """
        Create a new user group (admin only).

        **Parameters:**
        - **name**: Unique group name (1-100 chars)
        - **description**: Optional group description
        - **is_active**: Whether the group is active (default: true)

        **Example:**
        ```json
        {
          "name": "Premium Users",
          "description": "Users with premium subscription",
          "is_active": true
        }
        ```

        **Returns:** Created group with ID and metadata
        """
        service = UserGroupService(access_token=token)
        return await service.create_group(
            data=data, admin_id=admin_id, correlation_id=correlation_id
        )

    async def get_group(
        self,
        group_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserGroupDetailResponse:
        """
        Get detailed group information (admin only).

        Returns group with full list of members and assigned features.

        **Parameters:**
        - **group_id**: UUID of the group

        **Returns:** Group details including members and features
        """
        service = UserGroupService(access_token=token)
        return await service.get_group_detail(
            group_id=group_id, correlation_id=correlation_id
        )

    async def update_group(
        self,
        group_id: UUID,
        data: UserGroupUpdate,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> UserGroupResponse:
        """
        Update a user group (admin only).

        All fields are optional - only provided fields will be updated.

        **Parameters:**
        - **name**: New group name (must be unique)
        - **description**: New description
        - **is_active**: Active status

        **Example:**
        ```json
        {
          "name": "Premium Plus Users",
          "is_active": true
        }
        ```

        **Returns:** Updated group
        """
        service = UserGroupService(access_token=token)
        return await service.update_group(
            group_id=group_id, data=data, correlation_id=correlation_id
        )

    async def delete_group(
        self,
        group_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Delete a user group (admin only).

        This is a soft delete - the group is marked as inactive but not removed from the database.
        Members and feature assignments are preserved.

        **Parameters:**
        - **group_id**: UUID of the group to delete

        **Returns:** 204 No Content on success
        """
        service = UserGroupService(access_token=token)
        await service.delete_group(group_id=group_id, correlation_id=correlation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # =============================================
    # Member Management Endpoints
    # =============================================

    async def list_members(
        self,
        group_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[GroupMemberResponse]:
        """
        List all members of a group (admin only).

        **Parameters:**
        - **group_id**: UUID of the group

        **Returns:** List of group members with user details
        """
        service = UserGroupService(access_token=token)
        return await service.list_members(
            group_id=group_id, correlation_id=correlation_id
        )

    async def add_member(
        self,
        group_id: UUID,
        data: GroupMemberAdd,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> GroupMemberResponse:
        """
        Add a user to a group (admin only).

        **Parameters:**
        - **group_id**: UUID of the group
        - **user_id**: UUID of the user to add

        **Example:**
        ```json
        {
          "user_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        ```

        **Returns:** Created membership with user details
        """
        service = UserGroupService(access_token=token)
        return await service.add_member(
            group_id=group_id,
            data=data,
            admin_id=admin_id,
            correlation_id=correlation_id,
        )

    async def remove_member(
        self,
        group_id: UUID,
        user_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Remove a user from a group (admin only).

        This operation is idempotent - removing a non-existent member returns success.

        **Parameters:**
        - **group_id**: UUID of the group
        - **user_id**: UUID of the user to remove

        **Returns:** 204 No Content on success
        """
        service = UserGroupService(access_token=token)
        await service.remove_member(
            group_id=group_id, user_id=user_id, correlation_id=correlation_id
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # =============================================
    # Feature Management Endpoints
    # =============================================

    async def list_features(
        self,
        group_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[GroupFeatureResponse]:
        """
        List all features assigned to a group (admin only).

        **Parameters:**
        - **group_id**: UUID of the group

        **Returns:** List of features with their values
        """
        service = UserGroupService(access_token=token)
        return await service.list_features(
            group_id=group_id, correlation_id=correlation_id
        )

    async def assign_feature(
        self,
        group_id: UUID,
        data: GroupFeatureAssign,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> GroupFeatureResponse:
        """
        Assign a feature to a group (admin only).

        If the feature is already assigned, its value will be updated.

        **Parameters:**
        - **group_id**: UUID of the group
        - **feature_id**: UUID of the feature to assign
        - **value**: Feature value (bool for flags, int for quotas, dict for config)

        **Example (boolean flag):**
        ```json
        {
          "feature_id": "550e8400-e29b-41d4-a716-446655440000",
          "value": true
        }
        ```

        **Example (quota):**
        ```json
        {
          "feature_id": "550e8400-e29b-41d4-a716-446655440000",
          "value": 1000
        }
        ```

        **Example (config object):**
        ```json
        {
          "feature_id": "550e8400-e29b-41d4-a716-446655440000",
          "value": {
            "max_items": 100,
            "priority": "high"
          }
        }
        ```

        **Returns:** Feature assignment with details
        """
        service = UserGroupService(access_token=token)
        return await service.assign_feature(
            group_id=group_id,
            data=data,
            admin_id=admin_id,
            correlation_id=correlation_id,
        )

    async def revoke_feature(
        self,
        group_id: UUID,
        feature_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        """
        Revoke a feature from a group (admin only).

        This operation is idempotent - revoking a non-existent feature returns success.

        **Parameters:**
        - **group_id**: UUID of the group
        - **feature_id**: UUID of the feature to revoke

        **Returns:** 204 No Content on success
        """
        service = UserGroupService(access_token=token)
        await service.revoke_feature(
            group_id=group_id, feature_id=feature_id, correlation_id=correlation_id
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
