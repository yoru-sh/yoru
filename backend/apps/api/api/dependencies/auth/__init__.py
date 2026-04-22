"""Authentication dependencies.

Two auth vectors live side-by-side:

1. **Bearer JWT** — `get_current_user_id`, legacy CLI hook-token ingest path.
   Validates `Authorization: Bearer <token>` against Supabase. Kept for the CLI
   because CLI tools don't speak cookies.

2. **HttpOnly session cookie** — `get_current_user_id_from_cookie`, the only
   vector for dashboard users. The access-token JWT lives in the `rcpt_session`
   cookie set by `/auth/signin`; JS can never read it. CSRF protection lives in
   the `CsrfMiddleware` (double-submit cookie pattern).

The dashboard MUST use the cookie vector so that a compromised JS dependency
can't exfiltrate the token via `localStorage` or `document.cookie`.
"""

from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from libs.supabase.supabase import SupabaseManager

security = HTTPBearer()

SESSION_COOKIE_NAME = "rcpt_session"


async def get_current_user_id(
    request: Request,
) -> UUID:
    """
    Central auth dependency — accepts EITHER `rcpt_session` cookie (dashboard)
    or `Authorization: Bearer <jwt>` header (CLI / server-to-server). Returns
    the user UUID. 401 if neither path validates.

    Dashboard path: cookie set at `/auth/signin`, JWT unreadable by JavaScript.
    CLI path: callers explicitly attach the bearer header; CSRF is irrelevant
    because browsers never auto-attach header tokens cross-origin.
    """
    # Cookie path first — dashboard requests always carry the session cookie.
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        # Fallback to Authorization header for CLI / headless clients.
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supabase = SupabaseManager()
    try:
        user_response = supabase.client.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return UUID(user_response.user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_token(request: Request) -> str:
    """
    Return the raw JWT token for RLS-scoped Supabase calls — reads from
    cookie (dashboard) or Authorization header (CLI).
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


async def get_current_user_id_from_cookie(request: Request) -> UUID:
    """Validate the `rcpt_session` cookie and return the user UUID.

    This is the dashboard auth vector. The access-token JWT is read from a
    secure HttpOnly cookie — never from a header — so it is inaccessible to
    JavaScript. CSRF is handled separately by `CsrfMiddleware`.

    Raises:
        HTTPException: 401 if the cookie is missing, the token is invalid,
        or Supabase rejects it.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    supabase = SupabaseManager()
    try:
        user_response = supabase.client.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid session")
        return UUID(user_response.user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")


async def get_current_user_id_or_cookie(
    request: Request,
) -> UUID:
    """Accept EITHER the dashboard cookie OR a CLI bearer token.

    Use this on endpoints that serve both surfaces (e.g. health-deep, admin
    probes). For pure-dashboard endpoints prefer `get_current_user_id_from_cookie`
    so CSRF stays enforced.
    """
    # Prefer cookie when present (dashboard path, CSRF-checked by middleware).
    if SESSION_COOKIE_NAME in request.cookies:
        return await get_current_user_id_from_cookie(request)

    # Fall back to bearer for CLI callers.
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = auth_header.split(" ", 1)[1].strip()
    supabase = SupabaseManager()
    try:
        user_response = supabase.client.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return UUID(user_response.user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


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
