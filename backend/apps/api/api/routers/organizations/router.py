"""Organizations router for multi-tenancy system."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from libs.log_manager.controller import LoggingController
from apps.api.api.dependencies.auth import (
    get_correlation_id,
    get_current_user_id,
    get_current_user_token,
)
from apps.api.api.exceptions.domain_exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError,
    ValidationError,
)
from apps.api.api.models.organization.organization_models import (
    OrganizationCreate,
    OrganizationDetailResponse,
    OrganizationInvitationCreate,
    OrganizationInvitationPublicResponse,
    OrganizationInvitationResponse,
    OrganizationListResponse,
    OrganizationMemberAdd,
    OrganizationMemberResponse,
    OrganizationMemberUpdate,
    OrganizationResponse,
    OrganizationUpdate,
)
from apps.api.api.services.organization.organization_service import OrganizationService


class OrganizationsRouter:
    """Router for current user's organization management."""

    def __init__(self):
        self.logger = LoggingController(app_name="OrganizationsRouter")
        self.router = APIRouter(prefix="/me/organizations", tags=["me", "organizations"])
        self._setup_routes()

    def initialize_services(self) -> None:
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self) -> None:
        """Set up organization routes."""
        # Organization CRUD
        self.router.get("", response_model=OrganizationListResponse)(
            self.list_organizations
        )
        self.router.post(
            "",
            response_model=OrganizationResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.create_organization)
        self.router.get("/{org_id}", response_model=OrganizationDetailResponse)(
            self.get_organization
        )
        self.router.patch("/{org_id}", response_model=OrganizationResponse)(
            self.update_organization
        )
        self.router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)(
            self.delete_organization
        )

        # Member management
        self.router.get(
            "/{org_id}/members", response_model=list[OrganizationMemberResponse]
        )(self.list_members)
        self.router.post(
            "/{org_id}/members",
            response_model=OrganizationMemberResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.add_member)
        self.router.patch(
            "/{org_id}/members/{member_user_id}",
            response_model=OrganizationMemberResponse,
        )(self.update_member_role)
        self.router.delete(
            "/{org_id}/members/{member_user_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )(self.remove_member)

        # Invitation management
        self.router.get(
            "/{org_id}/invitations",
            response_model=list[OrganizationInvitationResponse],
        )(self.list_invitations)
        self.router.post(
            "/{org_id}/invitations",
            response_model=OrganizationInvitationResponse,
            status_code=status.HTTP_201_CREATED,
        )(self.create_invitation)
        self.router.delete(
            "/{org_id}/invitations/{invitation_id}",
            status_code=status.HTTP_204_NO_CONTENT,
        )(self.cancel_invitation)

    # =============================================
    # Organization CRUD Endpoints
    # =============================================

    async def list_organizations(
        self,
        request: Request,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=200, description="Items per page"),
        include_personal: bool = Query(
            True, description="Include personal organizations"
        ),
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationListResponse:
        """
        Get my organizations.

        List all organizations where I am a member.

        **Parameters:**
        - **page**: Page number (default: 1)
        - **page_size**: Items per page (default: 50, max: 200)
        - **include_personal**: Whether to include personal orgs (default: true)

        **Returns:** Paginated list of my organizations
        """
        service = OrganizationService(access_token=token)
        return await service.list_organizations(
            user_id=user_id,
            correlation_id=correlation_id,
            page=page,
            page_size=page_size,
            include_personal=include_personal,
        )

    async def create_organization(
        self,
        data: OrganizationCreate,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationResponse:
        """
        Create a new organization.

        The current user becomes the owner of the new organization.

        **Parameters:**
        - **name**: Organization name (1-100 chars)
        - **type**: Organization type (team or personal, default: team)
        - **avatar_url**: Optional avatar URL
        - **settings**: Optional settings object

        **Example:**
        ```json
        {
          "name": "My Team",
          "avatar_url": "https://example.com/avatar.png"
        }
        ```

        **Returns:** Created organization
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.create_organization(
                data=data, owner_id=user_id, correlation_id=correlation_id
            )
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=e.message) from e

    async def get_organization(
        self,
        org_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationDetailResponse:
        """
        Get detailed organization information.

        Returns organization with members and pending invitations (if admin/owner).

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** Organization details
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.get_organization_detail(
                org_id=org_id, user_id=user_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e

    async def update_organization(
        self,
        org_id: UUID,
        data: OrganizationUpdate,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationResponse:
        """
        Update an organization. Requires admin or owner role.

        **Parameters:**
        - **name**: New organization name
        - **avatar_url**: New avatar URL
        - **settings**: New settings object

        **Example:**
        ```json
        {
          "name": "New Team Name"
        }
        ```

        **Returns:** Updated organization
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.update_organization(
                org_id=org_id,
                data=data,
                user_id=user_id,
                correlation_id=correlation_id,
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e

    async def delete_organization(
        self,
        org_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> Response:
        """
        Delete an organization. Only the owner can delete.

        This is a soft delete with 30-day recovery period.
        Cannot delete personal organizations.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** 204 No Content on success
        """
        try:
            service = OrganizationService(access_token=token)
            await service.delete_organization(
                org_id=org_id, user_id=user_id, correlation_id=correlation_id
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.message) from e

    # =============================================
    # Member Management Endpoints
    # =============================================

    async def list_members(
        self,
        org_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[OrganizationMemberResponse]:
        """
        List all members of an organization.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** List of members with roles and user details
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.list_members(
                org_id=org_id, user_id=user_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e

    async def add_member(
        self,
        org_id: UUID,
        data: OrganizationMemberAdd,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationMemberResponse:
        """
        Add a user directly to an organization. Requires admin role.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **user_id**: UUID of the user to add
        - **role**: Role to assign (admin or member, default: member)

        **Example:**
        ```json
        {
          "user_id": "550e8400-e29b-41d4-a716-446655440000",
          "role": "member"
        }
        ```

        **Returns:** Created membership
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.add_member(
                org_id=org_id,
                data=data,
                user_id=user_id,
                correlation_id=correlation_id,
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=e.message) from e

    async def update_member_role(
        self,
        org_id: UUID,
        member_user_id: UUID,
        data: OrganizationMemberUpdate,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationMemberResponse:
        """
        Update a member's role. Requires admin role.

        Cannot change owner role.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **member_user_id**: UUID of the member to update
        - **role**: New role (admin or member)

        **Example:**
        ```json
        {
          "role": "admin"
        }
        ```

        **Returns:** Updated membership
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.update_member_role(
                org_id=org_id,
                member_user_id=member_user_id,
                data=data,
                user_id=user_id,
                correlation_id=correlation_id,
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.message) from e

    async def remove_member(
        self,
        org_id: UUID,
        member_user_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> Response:
        """
        Remove a member from an organization.

        Admins can remove members. Members can remove themselves (leave).
        Cannot remove the organization owner.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **member_user_id**: UUID of the member to remove

        **Returns:** 204 No Content on success
        """
        try:
            service = OrganizationService(access_token=token)
            await service.remove_member(
                org_id=org_id,
                member_user_id=member_user_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.message) from e

    # =============================================
    # Invitation Management Endpoints
    # =============================================

    async def list_invitations(
        self,
        org_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> list[OrganizationInvitationResponse]:
        """
        List pending invitations for an organization. Requires admin role.

        **Parameters:**
        - **org_id**: UUID of the organization

        **Returns:** List of pending invitations
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.list_invitations(
                org_id=org_id, user_id=user_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e

    async def create_invitation(
        self,
        org_id: UUID,
        data: OrganizationInvitationCreate,
        request: Request,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationInvitationResponse:
        """
        Create and send an invitation. Requires admin role.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **email**: Email address to invite
        - **role**: Role to assign on acceptance (admin or member, default: member)

        **Example:**
        ```json
        {
          "email": "user@example.com",
          "role": "member"
        }
        ```

        **Returns:** Created invitation with token
        """
        try:
            service = OrganizationService(access_token=token)
            return await service.create_invitation(
                org_id=org_id,
                data=data,
                user_id=user_id,
                correlation_id=correlation_id,
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=e.message) from e

    async def cancel_invitation(
        self,
        org_id: UUID,
        invitation_id: UUID,
        user_id: UUID = Depends(get_current_user_id),
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> Response:
        """
        Cancel a pending invitation. Requires admin role.

        **Parameters:**
        - **org_id**: UUID of the organization
        - **invitation_id**: UUID of the invitation

        **Returns:** 204 No Content on success
        """
        try:
            service = OrganizationService(access_token=token)
            await service.cancel_invitation(
                org_id=org_id,
                invitation_id=invitation_id,
                user_id=user_id,
                correlation_id=correlation_id,
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=e.message) from e


class InvitationsPublicRouter:
    """Router for public invitation endpoints."""

    def __init__(self):
        self.logger = LoggingController(app_name="InvitationsPublicRouter")
        self.router = APIRouter(prefix="/invitations", tags=["invitations"])
        self._setup_routes()

    def initialize_services(self) -> None:
        """Initialize required services - not used as services are created per-request."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router."""
        return self.router

    def _setup_routes(self) -> None:
        """Set up public invitation routes."""
        self.router.get(
            "/{token}", response_model=OrganizationInvitationPublicResponse
        )(self.get_invitation)
        self.router.post("/{token}/accept", response_model=OrganizationResponse)(
            self.accept_invitation
        )

    async def get_invitation(
        self,
        token: str,
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationInvitationPublicResponse:
        """
        Get invitation information by token.

        This endpoint is public and can be accessed without authentication
        to display invitation details before sign up.

        **Parameters:**
        - **token**: Invitation token from email link

        **Returns:** Public invitation info (org name, inviter, etc.)
        """
        try:
            service = OrganizationService()
            return await service.get_invitation_by_token(
                token=token, correlation_id=correlation_id
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.message) from e

    async def accept_invitation(
        self,
        token: str,
        user_id: UUID = Depends(get_current_user_id),
        access_token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ) -> OrganizationResponse:
        """
        Accept an invitation and join the organization.

        Requires authentication. The email of the authenticated user
        must match the invitation email.

        **Parameters:**
        - **token**: Invitation token from email link

        **Returns:** The organization the user joined
        """
        try:
            service = OrganizationService(access_token=access_token)
            return await service.accept_invitation(
                token=token, user_id=user_id, correlation_id=correlation_id
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
        except ConflictError as e:
            raise HTTPException(status_code=409, detail=e.message) from e
