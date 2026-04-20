"""Rate limiting middleware with dynamic feature-based limits."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.api.api.config.middleware_settings import get_middleware_settings
from libs.resilience.rate_limiter import RateLimiter, RateLimitExceededError
from libs.log_manager.controller import LoggingController
from libs.supabase.supabase import SupabaseManager


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with dynamic feature-based limits.

    Features:
    - Per-user + per-endpoint rate limiting
    - Dynamic limits via Supabase feature system (features table)
    - IP-based limiting for unauthenticated requests
    - X-RateLimit-* headers in responses
    - Graceful degradation on Redis errors

    Rate limit hierarchy (via Supabase feature system):
    1. user_grants - Admin overrides for specific users
    2. user_group_features - Features via group membership
    3. plan_features - Features via subscription plan (free/pro/enterprise)
    4. default_value - Feature default value

    Integration with RBAC:
    - Uses the same hierarchical feature system as RBAC
    - Checks "rate_limit_per_minute" feature for each user
    - Falls back to default limit if feature not configured

    Compliance:
    - python.state.rules.md BLOC-002: Settings via pydantic-settings
    """

    FEATURE_KEY = "rate_limit_per_minute"  # Feature key in Supabase

    def __init__(
        self,
        app,
        enabled: bool = True,
        default_limit: int = 100,
        window_seconds: int = 60,
        supabase: SupabaseManager = None
    ):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application instance
            enabled: Enable rate limiting (default: True, or from MiddlewareSettings)
            default_limit: Default requests per window if feature not configured (default: 100)
            window_seconds: Time window in seconds (default: from MiddlewareSettings or 60)
            supabase: Optional SupabaseManager instance
        """
        super().__init__(app)

        # Get settings
        settings = get_middleware_settings()

        # Check enabled flag
        self.enabled = enabled and settings.enable_rate_limiting

        self.rate_limiter = RateLimiter()
        self.supabase = supabase or SupabaseManager()
        self.window_seconds = settings.rate_limit_window_seconds
        self.default_limit = settings.rate_limit_free_plan  # Use free plan as default
        self.unauthenticated_limit = settings.rate_limit_unauthenticated
        self.logger = LoggingController(app_name="RateLimitMiddleware")

        if self.enabled:
            self.logger.log_info(
                "Rate limiting enabled with dynamic feature-based limits",
                {
                    "window_seconds": self.window_seconds,
                    "default_limit": self.default_limit,
                    "unauthenticated_limit": self.unauthenticated_limit,
                    "feature_key": self.FEATURE_KEY,
                }
            )
        else:
            self.logger.log_info("Rate limiting disabled")

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request with rate limiting using Supabase feature system.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response with X-RateLimit-* headers
        """
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for excluded paths
        if self._should_skip_path(request.url.path):
            return await call_next(request)

        # Get correlation ID
        correlation_id = getattr(request.state, "correlation_id", "")

        # Determine rate limit key and limit
        user_id = getattr(request.state, "user_id", None)

        if user_id:
            # Authenticated user - get limit from Supabase feature system
            limit = await self._get_user_rate_limit(user_id, correlation_id)

            # Per-user + per-endpoint key for granular limiting
            key = f"ratelimit:user:{user_id}:endpoint:{request.url.path}"
        else:
            # Unauthenticated - use hardcoded limit for security
            client_ip = request.client.host if request.client else "unknown"
            limit = self.unauthenticated_limit
            key = f"ratelimit:ip:{client_ip}"

        # Check rate limit
        allowed, remaining, reset_timestamp = await self.rate_limiter.check_rate_limit(
            key=key,
            limit=limit,
            window_seconds=self.window_seconds,
            correlation_id=correlation_id
        )

        # Log rate limit check
        self.logger.log_debug(
            "Rate limit check",
            {
                "correlation_id": correlation_id,
                "user_id": user_id,
                "path": request.url.path,
                "allowed": allowed,
                "remaining": remaining,
                "limit": limit,
            }
        )

        if not allowed:
            # Rate limit exceeded - return 429
            import time
            retry_after = reset_timestamp - int(time.time())

            self.logger.log_warning(
                "Rate limit exceeded",
                {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "path": request.url.path,
                    "limit": limit,
                }
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Maximum {limit} requests per {self.window_seconds} seconds.",
                    "retry_after": retry_after,
                },
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_timestamp),
                    "Retry-After": str(retry_after),
                }
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_timestamp)

        return response

    def _should_skip_path(self, path: str) -> bool:
        """
        Check if path should skip rate limiting.

        Args:
            path: Request path

        Returns:
            True if path should be skipped
        """
        # Paths to exclude from rate limiting
        excluded_paths = {
            "/health",
            "/api/ping",
            "/api/docs",
            "/api/openapi.json",
            "/api/redoc",
        }

        return path in excluded_paths

    async def _get_user_rate_limit(self, user_id: str, correlation_id: str) -> int:
        """
        Get user's rate limit using hierarchical Supabase feature system.

        Priority order (same as RBAC):
        1. user_grants - Admin overrides for specific users
        2. user_group_features - Features via group membership
        3. plan_features - Features via subscription plan
        4. default_value - Feature default value

        Args:
            user_id: User ID
            correlation_id: Request correlation ID

        Returns:
            Rate limit (requests per window)
        """
        context = {
            "operation": "get_user_rate_limit",
            "component": "RateLimitMiddleware",
            "correlation_id": correlation_id,
            "user_id": user_id,
            "feature_key": self.FEATURE_KEY,
        }

        try:
            # Get feature details
            features = self.supabase.query_records(
                "features",
                filters={"key": self.FEATURE_KEY},
                correlation_id=correlation_id,
            )
            if not features:
                self.logger.log_warning(
                    "Rate limit feature not found, using default",
                    {**context, "default_limit": self.default_limit}
                )
                return self.default_limit

            feature = features[0]
            feature_id = feature["id"]

            # 1. Check user_grants (highest priority)
            grants = self.supabase.query_records(
                "user_grants",
                filters={"user_id": user_id, "feature_id": feature_id},
                correlation_id=correlation_id,
            )
            if grants:
                grant = grants[0]
                # Check if grant is expired
                if grant.get("expires_at"):
                    from datetime import datetime, timezone
                    expires_at = datetime.fromisoformat(
                        grant["expires_at"].replace("Z", "+00:00")
                    )
                    if expires_at <= datetime.now(timezone.utc):
                        self.logger.log_debug(
                            "User grant expired",
                            {**context, "expires_at": grant["expires_at"]},
                        )
                    else:
                        limit = self._extract_limit_from_value(grant["value"])
                        self.logger.log_debug(
                            "Rate limit from user_grants",
                            {**context, "source": "user_grants", "limit": limit},
                        )
                        return limit
                else:
                    # No expiration, grant is active
                    limit = self._extract_limit_from_value(grant["value"])
                    self.logger.log_debug(
                        "Rate limit from user_grants",
                        {**context, "source": "user_grants", "limit": limit},
                    )
                    return limit

            # 2. Check user_group_features (via group membership)
            try:
                group_feature = (
                    self.supabase.client.rpc(
                        "get_user_feature_via_groups",
                        {"p_user_id": user_id, "p_feature_key": self.FEATURE_KEY},
                    )
                    .execute()
                )
                if group_feature.data and len(group_feature.data) > 0:
                    value = group_feature.data[0]["value"]
                    limit = self._extract_limit_from_value(value)
                    self.logger.log_debug(
                        "Rate limit from user_groups",
                        {**context, "source": "user_groups", "limit": limit},
                    )
                    return limit
            except Exception as e:
                self.logger.log_warning(
                    "Error checking group features",
                    {**context, "error": str(e)},
                )
                # Continue to next priority level

            # 3. Check plan_features (via subscription)
            subscriptions = self.supabase.query_records(
                "subscriptions",
                filters={"user_id": user_id, "status": "active"},
                correlation_id=correlation_id,
            )
            if subscriptions:
                # Get most recent active subscription
                subscription = sorted(
                    subscriptions, key=lambda x: x.get("created_at", ""), reverse=True
                )[0]

                plan_features = self.supabase.query_records(
                    "plan_features",
                    filters={
                        "plan_id": subscription["plan_id"],
                        "feature_id": feature_id,
                    },
                    correlation_id=correlation_id,
                )
                if plan_features:
                    value = plan_features[0]["value"]
                    limit = self._extract_limit_from_value(value)
                    self.logger.log_debug(
                        "Rate limit from plan_features",
                        {**context, "source": "plan_features", "limit": limit},
                    )
                    return limit

            # 4. Check default_value (lowest priority)
            default_value = feature.get("default_value")
            if default_value is not None:
                limit = self._extract_limit_from_value(default_value)
                self.logger.log_debug(
                    "Rate limit from default_value",
                    {**context, "source": "default_value", "limit": limit},
                )
                return limit

            # Fallback to configured default
            self.logger.log_warning(
                "No rate limit found at any level, using configured default",
                {**context, "default_limit": self.default_limit}
            )
            return self.default_limit

        except Exception as e:
            self.logger.log_error(
                "Error getting user rate limit, using default",
                context,
                e,
            )
            # On error, use default limit (fail open)
            return self.default_limit

    def _extract_limit_from_value(self, value) -> int:
        """
        Extract limit from feature value.

        The value can be:
        - {"limit": 100} (jsonb format)
        - 100 (direct integer)
        - "100" (string)

        Args:
            value: Feature value from Supabase

        Returns:
            Extracted limit as integer
        """
        try:
            if isinstance(value, dict):
                # Extract from {"limit": 100}
                return int(value.get("limit", self.default_limit))
            elif isinstance(value, int):
                return value
            elif isinstance(value, str):
                return int(value)
            else:
                self.logger.log_warning(
                    f"Unexpected rate limit value type: {type(value)}",
                    {"value": value}
                )
                return self.default_limit
        except (ValueError, TypeError) as e:
            self.logger.log_error(
                f"Error extracting limit from value: {e}",
                {"value": value}
            )
            return self.default_limit
