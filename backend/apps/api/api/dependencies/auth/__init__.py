"""Authentication dependencies."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from libs.supabase.supabase import SupabaseManager

security = HTTPBearer()


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UUID:
    """
    FastAPI dependency that validates the Bearer token and returns the user ID.

    Extracts the JWT token from the Authorization header, validates it
    with Supabase Auth, and returns the user's UUID.

    Args:
        request: The FastAPI request object
        credentials: The HTTP Bearer credentials

    Returns:
        UUID of the authenticated user

    Raises:
        HTTPException: 401 if authentication fails
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    supabase = SupabaseManager()

    try:
        # Validate token with Supabase Auth
        user_response = supabase.client.auth.get_user(token)

        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=401,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return UUID(user_response.user.id)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    FastAPI dependency that returns the JWT token from the Authorization header.

    Args:
        credentials: The HTTP Bearer credentials

    Returns:
        The JWT token string

    Raises:
        HTTPException: 401 if authentication required
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


async def get_correlation_id(request: Request) -> str:
    """
    FastAPI dependency that returns the correlation ID from request state.

    Args:
        request: The FastAPI request object

    Returns:
        The correlation ID string
    """
    return getattr(request.state, "correlation_id", "")


async def require_auth(
    user_id: UUID = Depends(get_current_user_id),
) -> UUID:
    """
    FastAPI dependency that requires authentication.

    Args:
        user_id: The authenticated user ID

    Returns:
        UUID of the authenticated user

    Raises:
        HTTPException: 401 if not authenticated
    """
    return user_id


async def require_admin(
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    token: str = Depends(get_current_user_token),
) -> UUID:
    """
    FastAPI dependency that requires admin role.

    Args:
        request: The FastAPI request object
        user_id: The authenticated user ID
        token: The JWT token

    Returns:
        UUID of the authenticated admin user

    Raises:
        HTTPException: 403 if user is not an admin
    """
    supabase = SupabaseManager(access_token=token)

    try:
        # Get user profile to check role
        correlation_id = getattr(request.state, "correlation_id", "")
        profile = supabase.get_record(
            "profiles", str(user_id), correlation_id=correlation_id
        )

        if not profile or profile.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Admin access required",
            )

        return user_id

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=403,
            detail="Unable to verify admin access",
        )
