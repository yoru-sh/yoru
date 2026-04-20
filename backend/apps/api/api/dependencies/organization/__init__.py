"""Organization dependencies for multi-tenancy system."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request

from libs.supabase.supabase import SupabaseManager
from apps.api.api.dependencies.auth import get_current_user_id, get_current_user_token
from apps.api.api.models.organization.organization_models import OrganizationRole


async def get_organization_id(
    request: Request,
    x_organization_id: str | None = Header(None, alias="X-Organization-Id"),
    org_id: str | None = None,
    user_id: UUID = Depends(get_current_user_id),
    token: str = Depends(get_current_user_token),
) -> UUID:
    """
    FastAPI dependency that returns the organization context.

    Organization can be specified via:
    1. X-Organization-Id header
    2. org_id query parameter
    3. Auto-inferred if user has only one organization

    Args:
        request: The FastAPI request object
        x_organization_id: Organization ID from header
        org_id: Organization ID from query parameter
        user_id: The authenticated user ID
        token: The JWT token

    Returns:
        UUID of the organization

    Raises:
        HTTPException: 400 if organization context required but not provided
    """
    # Check header first
    org_id_str = x_organization_id or org_id

    supabase = SupabaseManager(access_token=token)
    correlation_id = getattr(request.state, "correlation_id", "")

    if org_id_str:
        # Validate org_id format
        try:
            return UUID(org_id_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid organization ID format",
            )

    # Auto-infer if user has only one organization
    try:
        memberships = supabase.query_records(
            "organization_members",
            filters={"user_id": str(user_id)},
            correlation_id=correlation_id,
        )

        if not memberships:
            raise HTTPException(
                status_code=400,
                detail="No organization found. Please create an organization first.",
            )

        # Filter to non-deleted orgs
        valid_orgs = []
        for membership in memberships:
            org = supabase.get_record(
                "organizations",
                membership["org_id"],
                correlation_id=correlation_id,
            )
            if org and not org.get("deleted_at"):
                valid_orgs.append(membership["org_id"])

        if len(valid_orgs) == 1:
            return UUID(valid_orgs[0])

        if len(valid_orgs) == 0:
            raise HTTPException(
                status_code=400,
                detail="No organization found. Please create an organization first.",
            )

        # Multiple orgs - require explicit selection
        raise HTTPException(
            status_code=400,
            detail="Organization context required. Provide X-Organization-Id header.",
        )

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to determine organization context",
        )


async def require_org_member(
    request: Request,
    org_id: UUID = Depends(get_organization_id),
    user_id: UUID = Depends(get_current_user_id),
    token: str = Depends(get_current_user_token),
) -> tuple[UUID, OrganizationRole]:
    """
    FastAPI dependency that requires user to be a member of the organization.

    Args:
        request: The FastAPI request object
        org_id: The organization ID
        user_id: The authenticated user ID
        token: The JWT token

    Returns:
        Tuple of (org_id, user_role)

    Raises:
        HTTPException: 403 if user is not a member
    """
    supabase = SupabaseManager(access_token=token)
    correlation_id = getattr(request.state, "correlation_id", "")

    try:
        # Check organization exists
        org = supabase.get_record(
            "organizations", str(org_id), correlation_id=correlation_id
        )
        if not org or org.get("deleted_at"):
            raise HTTPException(
                status_code=404,
                detail="Organization not found",
            )

        # Check membership
        memberships = supabase.query_records(
            "organization_members",
            filters={"org_id": str(org_id), "user_id": str(user_id)},
            correlation_id=correlation_id,
        )

        if not memberships:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this organization",
            )

        role = OrganizationRole(memberships[0]["role"])

        # Store in request state for later use
        request.state.org_id = org_id
        request.state.org_role = role

        return (org_id, role)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to verify organization membership",
        )


async def require_org_admin(
    request: Request,
    org_id: UUID = Depends(get_organization_id),
    user_id: UUID = Depends(get_current_user_id),
    token: str = Depends(get_current_user_token),
) -> tuple[UUID, OrganizationRole]:
    """
    FastAPI dependency that requires user to be admin or owner of the organization.

    Args:
        request: The FastAPI request object
        org_id: The organization ID
        user_id: The authenticated user ID
        token: The JWT token

    Returns:
        Tuple of (org_id, user_role)

    Raises:
        HTTPException: 403 if user is not admin/owner
    """
    supabase = SupabaseManager(access_token=token)
    correlation_id = getattr(request.state, "correlation_id", "")

    try:
        # Check organization exists
        org = supabase.get_record(
            "organizations", str(org_id), correlation_id=correlation_id
        )
        if not org or org.get("deleted_at"):
            raise HTTPException(
                status_code=404,
                detail="Organization not found",
            )

        # Check membership
        memberships = supabase.query_records(
            "organization_members",
            filters={"org_id": str(org_id), "user_id": str(user_id)},
            correlation_id=correlation_id,
        )

        if not memberships:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this organization",
            )

        role = OrganizationRole(memberships[0]["role"])

        if role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
            raise HTTPException(
                status_code=403,
                detail="Admin or owner role required",
            )

        # Store in request state for later use
        request.state.org_id = org_id
        request.state.org_role = role

        return (org_id, role)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to verify organization admin access",
        )


async def require_org_owner(
    request: Request,
    org_id: UUID = Depends(get_organization_id),
    user_id: UUID = Depends(get_current_user_id),
    token: str = Depends(get_current_user_token),
) -> UUID:
    """
    FastAPI dependency that requires user to be owner of the organization.

    Args:
        request: The FastAPI request object
        org_id: The organization ID
        user_id: The authenticated user ID
        token: The JWT token

    Returns:
        The organization ID

    Raises:
        HTTPException: 403 if user is not owner
    """
    supabase = SupabaseManager(access_token=token)
    correlation_id = getattr(request.state, "correlation_id", "")

    try:
        # Check organization exists and user is owner
        org = supabase.get_record(
            "organizations", str(org_id), correlation_id=correlation_id
        )
        if not org or org.get("deleted_at"):
            raise HTTPException(
                status_code=404,
                detail="Organization not found",
            )

        if org["owner_id"] != str(user_id):
            raise HTTPException(
                status_code=403,
                detail="Owner role required",
            )

        # Store in request state for later use
        request.state.org_id = org_id
        request.state.org_role = OrganizationRole.OWNER

        return org_id

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to verify organization owner access",
        )
