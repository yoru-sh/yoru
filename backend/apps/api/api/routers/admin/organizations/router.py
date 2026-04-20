"""Admin router for system-wide organization management."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import (
    get_correlation_id,
    get_current_user_token,
    require_admin,
)
from apps.api.api.exceptions.domain_exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError,
    ValidationError,
)
from apps.api.api.models.organization.organization_models import (
    OrganizationDetailResponse,
    OrganizationListResponse,
    OrganizationMemberResponse,
    OrganizationResponse,
    OrganizationUpdate,
)
from apps.api.api.services.organization.organization_service import OrganizationService


class AdminOrganizationsRouter:
    """Router for admin organization management (system-wide)."""

    def __init__(self):
        self.logger = LoggingController(app_name="AdminOrganizationsRouter")
        self.router = APIRouter(
            prefix="/admin/organizations", tags=["admin", "organizations"]
        )
        self._setup_routes()

    def initialize_services(self) -> None:
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self) -> None:
        """Set up admin organization routes."""
        # Organization CRUD (admin can manage any org)
        self.router.get("", response_model=OrganizationListResponse)(
            self.list_all_organizations
        )
        self.router.get("/{org_id}", response_model=OrganizationDetailResponse)(
            self.get_organization
        )
        self.router.patch("/{org_id}", response_model=OrganizationResponse)(
            self.update_organization
        )
        self.router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)(
            self.delete_organization
        )

        # Member management (admin can view members of any org)
        self.router.get(
            "/{org_id}/members", response_model=list[OrganizationMemberResponse]
        )(self.list_members)

    # =============================================
    # Organization CRUD Endpoints
    # =============================================

    async def list_all_organizations(
        self,
        request: Request,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=200, description="Items per page"),
        org_type: str | None = Query(
            None, description="Filter by type (personal or team)"
        ),
        include_deleted: bool = Query(
            False, description="Include soft-deleted organizations"
        ),
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationListResponse:
        """
        List all organizations in the system (admin only).

        Returns paginated list of all organizations with filtering options.

        **Parameters:**
        - **page**: Page number (default: 1)
        - **page_size**: Items per page (default: 50, max: 200)
        - **org_type**: Filter by type - "personal" or "team" (optional)
        - **include_deleted**: Include soft-deleted organizations (default: false)

        **Returns:**
        - **items**: List of organizations
        - **total**: Total number of organizations
        - **page**: Current page number
        - **page_size**: Items per page
        - **total_pages**: Total number of pages
        """
        service = OrganizationService(access_token=token)

        # Admin can see all organizations
        # We need to query directly from database for admin view
        # For now, use a special method in the service
        return await service.list_all_organizations_admin(
            correlation_id=correlation_id,
            page=page,
            page_size=page_size,
            org_type=org_type,
            include_deleted=include_deleted,
        )

    async def get_organization(
        self,
        org_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationDetailResponse:
        """
        Get detailed organization information (admin only).

        Admin can view any organization in the system, including members and invitations.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** Organization details with members and pending invitations
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.get_organization_detail_admin(
                org_id=org_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=e.message) from e

    async def update_organization(
        self,
        org_id: UUID,
        data: OrganizationUpdate,
        request: Request,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationResponse:
        """
        Update any organization (admin only).

        Admin can update any organization's settings regardless of membership.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **name**: New organization name
        - **avatar_url**: New avatar URL
        - **settings**: New settings object

        **Example:**
        ```json
        {
          "name": "Updated Organization Name"
        }
        ```

        **Returns:** Updated organization
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.update_organization_admin(
                org_id=org_id, data=data, correlation_id=correlation_id
            )
        except NotFoundError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_organization(
        self,
        org_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> Response:
        """
        Delete any organization (admin only).

        This is a soft delete with 30-day recovery period.
        Admin can delete any organization, including personal organizations.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** 204 No Content on success
        """
        try:
            service = OrganizationService(access_token=token)
            await service.delete_organization_admin(
                org_id=org_id, correlation_id=correlation_id
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=e.message) from e

    # =============================================
    # Member Management Endpoints
    # =============================================

    async def list_members(
        self,
        org_id: UUID,
        admin_id: UUID = Depends(require_admin),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[OrganizationMemberResponse]:
        """
        List all members of any organization (admin only).

        Admin can view members of any organization regardless of their own membership.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** List of members with roles and user details
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.list_members_admin(
                org_id=org_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=e.message) from e
