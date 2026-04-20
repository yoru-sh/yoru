"""Organization context middleware for multi-tenancy system."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from tenacity import retry, stop_after_attempt, wait_exponential

from libs.log_manager.controller import LoggingController
from libs.supabase.supabase import SupabaseManager


class OrganizationContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles organization context for multi-tenancy.

    Features:
    - Extracts X-Organization-Id from incoming request headers
    - Auto-infers organization if user has only one
    - Stores org_id and org_role in request.state for downstream access
    - Transparent for B2C users with single personal org

    This middleware is optional and non-blocking by default.
    Use the organization dependencies for strict enforcement.

    Configuration:
    - excluded_paths: List of path prefixes to skip (e.g., /auth, /health)
    - require_org: If True, returns 400 for requests without org context
    """

    def __init__(
        self,
        app,
        excluded_paths: list[str] | None = None,
        require_org: bool = False,
    ):
        super().__init__(app)
        self.logger = LoggingController(app_name="OrganizationContextMiddleware")
        self.excluded_paths = excluded_paths or [
            "/api/v1/auth",
            "/api/v1/invitations",
            "/api/ping",
            "/api/v1/heartbeat",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.require_org = require_org

    async def dispatch(self, request: Request, call_next):
        """Process the request and set organization context."""
        # Initialize state attributes
        request.state.org_id = None
        request.state.org_role = None
        request.state.user_id = None
        request.state.plan = None

        # Skip excluded paths
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.excluded_paths):
            return await call_next(request)

        # Try to get organization context
        correlation_id = getattr(request.state, "correlation_id", "")

        # Extract user_id and token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        token = None

        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            user_id = await self._extract_user_from_token(token, correlation_id)

            if user_id:
                # Set user_id in request.state for downstream middlewares
                request.state.user_id = str(user_id)

                # Get user's subscription plan
                plan = await self._get_user_subscription_plan(
                    user_id, token, correlation_id
                )
                if plan:
                    request.state.plan = plan

        # Check for X-Organization-Id header
        org_id_header = request.headers.get("X-Organization-Id")

        # Also check query parameter as fallback
        org_id_param = request.query_params.get("org_id")

        org_id_str = org_id_header or org_id_param

        if org_id_str:
            # Validate UUID format
            try:
                org_id = UUID(org_id_str)
                request.state.org_id = org_id
            except ValueError:
                if self.require_org:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid organization ID format"},
                    )
                # If not required, just continue without context
                return await call_next(request)

        # If no org_id provided, try to auto-infer from user
        if not request.state.org_id and request.state.user_id and token:
            org_id = await self._try_infer_organization_from_user(
                UUID(request.state.user_id), token, correlation_id
            )
            if org_id:
                request.state.org_id = org_id
            elif self.require_org:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Organization context required. Provide X-Organization-Id header."
                    },
                )

        # If we have an org_id, validate membership and get role
        if request.state.org_id and request.state.user_id and token:
            role = await self._get_user_role_in_org(
                UUID(request.state.user_id),
                request.state.org_id,
                token,
                correlation_id
            )
            if role:
                request.state.org_role = role
            elif self.require_org:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "You are not a member of this organization"},
                )

        return await call_next(request)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True
    )
    async def _extract_user_from_token(
        self, token: str, correlation_id: str
    ) -> UUID | None:
        """
        Extract user ID from JWT token with retry.

        Args:
            token: JWT access token
            correlation_id: Request correlation ID

        Returns:
            User UUID or None if token is invalid

        Compliance:
            - scale.resilience.rules.md BLOC-RES-003: Retry avec backoff exponentiel
        """
        try:
            supabase = SupabaseManager(access_token=token)
            user_response = supabase.client.auth.get_user(token)

            if not user_response or not user_response.user:
                return None

            return UUID(user_response.user.id)

        except Exception as e:
            self.logger.log_debug(
                "Failed to extract user from token",
                {
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=False  # Don't reraise, return "free" on final failure
    )
    async def _get_user_subscription_plan(
        self, user_id: UUID, token: str, correlation_id: str
    ) -> str | None:
        """
        Get user's active subscription plan with retry.

        Args:
            user_id: User UUID
            token: JWT access token
            correlation_id: Request correlation ID

        Returns:
            Plan name (e.g., "free", "pro", "enterprise") or None

        Compliance:
            - scale.resilience.rules.md BLOC-RES-003: Retry avec backoff exponentiel
        """
        try:
            supabase = SupabaseManager(access_token=token)

            # Get active subscription
            subscriptions = supabase.query_records(
                "subscriptions",
                filters={"user_id": str(user_id), "status": "active"},
                correlation_id=correlation_id,
            )

            if not subscriptions:
                return "free"  # Default to free plan if no active subscription

            # Get most recent active subscription
            subscription = sorted(
                subscriptions, key=lambda x: x.get("created_at", ""), reverse=True
            )[0]

            # Get plan details
            plan = supabase.get_record(
                "plans",
                subscription["plan_id"],
                correlation_id=correlation_id,
            )

            if plan:
                return plan.get("name", "free").lower()

            return "free"

        except Exception as e:
            self.logger.log_warning(
                "Failed to get user subscription plan",
                {
                    "correlation_id": correlation_id,
                    "user_id": str(user_id),
                    "error": str(e),
                },
            )
            return "free"  # Default to free on error

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=False
    )
    async def _try_infer_organization_from_user(
        self, user_id: UUID, token: str, correlation_id: str
    ) -> UUID | None:
        """
        Try to infer organization from user's memberships with retry.

        Args:
            user_id: User UUID
            token: JWT access token
            correlation_id: Request correlation ID

        Returns:
            Organization UUID or None if cannot infer

        Compliance:
            - scale.resilience.rules.md BLOC-RES-003: Retry avec backoff exponentiel
        """
        try:
            supabase = SupabaseManager(access_token=token)

            # Get user's organization memberships
            memberships = supabase.query_records(
                "organization_members",
                filters={"user_id": str(user_id)},
                correlation_id=correlation_id,
            )

            if not memberships:
                return None

            # Filter to non-deleted organizations
            valid_org_ids = []
            for membership in memberships:
                org = supabase.get_record(
                    "organizations",
                    membership["org_id"],
                    correlation_id=correlation_id,
                )
                if org and not org.get("deleted_at"):
                    valid_org_ids.append(membership["org_id"])

            # Auto-select if user has exactly one organization
            if len(valid_org_ids) == 1:
                return UUID(valid_org_ids[0])

            return None

        except Exception as e:
            self.logger.log_warning(
                "Failed to infer organization",
                {
                    "correlation_id": correlation_id,
                    "user_id": str(user_id),
                    "error": str(e),
                },
            )
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=False
    )
    async def _get_user_role_in_org(
        self,
        user_id: UUID,
        org_id: UUID,
        token: str,
        correlation_id: str
    ) -> str | None:
        """
        Get user's role in the organization with retry.

        Args:
            user_id: User UUID
            org_id: Organization UUID
            token: JWT access token
            correlation_id: Request correlation ID

        Returns:
            Role name or None if not a member

        Compliance:
            - scale.resilience.rules.md BLOC-RES-003: Retry avec backoff exponentiel
        """
        try:
            supabase = SupabaseManager(access_token=token)

            # Get membership
            memberships = supabase.query_records(
                "organization_members",
                filters={"org_id": str(org_id), "user_id": str(user_id)},
                correlation_id=correlation_id,
            )

            if memberships:
                return memberships[0]["role"]

            return None

        except Exception as e:
            self.logger.log_warning(
                "Failed to get user role",
                {
                    "correlation_id": correlation_id,
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "error": str(e),
                },
            )
            return None
