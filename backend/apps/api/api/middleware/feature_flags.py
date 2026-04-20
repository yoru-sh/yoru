"""Feature flags middleware for kill switches and circuit breakers."""

import os
from datetime import datetime
from typing import Dict, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.api.api.config.middleware_settings import get_middleware_settings
from libs.log_manager.controller import LoggingController


class FeatureFlagsMiddleware(BaseHTTPMiddleware):
    """
    Middleware for feature flags and kill switches.

    Features:
    - Global API kill switch (emergency shutdown)
    - Per-endpoint kill switches
    - Maintenance mode
    - In-memory cache with TTL for performance
    - Falls back to env vars if Redis unavailable

    This middleware should be placed early in the stack (after CORS/Security)
    to prevent unnecessary processing when features are disabled.

    Configuration:
    - API_ENABLED: Global API on/off switch (default: true)
    - MAINTENANCE_MODE: Put API in maintenance mode (default: false)
    - FEATURE_FLAGS_TTL_SECONDS: Cache TTL for flags (default: 10)

    Kill switch usage:
    1. Emergency shutdown: Set API_ENABLED=false in env
    2. Maintenance mode: Set MAINTENANCE_MODE=true in env
    3. Per-endpoint: Set DISABLE_ENDPOINT_/path/to/endpoint=true in env

    Compliance:
    - python.state.rules.md BLOC-002: Settings via pydantic-settings
    """

    def __init__(self, app):
        """Initialize feature flags middleware."""
        super().__init__(app)
        self.logger = LoggingController(app_name="FeatureFlagsMiddleware")

        # Get settings
        self.settings = get_middleware_settings()

        # Cache for feature flags
        self._flags_cache: Dict[str, bool] = {}
        self._cache_timestamp: Optional[datetime] = None

        # Cache TTL (how often to refresh from env/redis)
        self.cache_ttl_seconds = self.settings.feature_flags_ttl_seconds

        self.logger.log_info("Feature flags middleware enabled")

    async def dispatch(self, request: Request, call_next):
        """
        Process request with feature flag checks.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response or 503 if feature is disabled
        """
        correlation_id = getattr(request.state, "correlation_id", "")

        # Refresh cache if expired
        await self._refresh_cache_if_needed()

        # Check global kill switch
        if not self._is_api_enabled():
            self.logger.log_warning(
                "API disabled via kill switch",
                {
                    "correlation_id": correlation_id,
                    "path": request.url.path,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_unavailable",
                    "message": "API is temporarily disabled",
                },
            )

        # Check maintenance mode
        if self._is_maintenance_mode():
            # Allow health check endpoints during maintenance
            if request.url.path in ["/health", "/api/ping"]:
                return await call_next(request)

            self.logger.log_info(
                "Request blocked: maintenance mode",
                {
                    "correlation_id": correlation_id,
                    "path": request.url.path,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "maintenance_mode",
                    "message": "API is under maintenance. Please try again later.",
                },
            )

        # Check per-endpoint kill switches
        if self._is_endpoint_disabled(request.url.path):
            self.logger.log_warning(
                "Endpoint disabled via kill switch",
                {
                    "correlation_id": correlation_id,
                    "path": request.url.path,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "endpoint_disabled",
                    "message": f"Endpoint {request.url.path} is temporarily disabled",
                },
            )

        # All checks passed, continue processing
        return await call_next(request)

    async def _refresh_cache_if_needed(self):
        """Refresh feature flags cache if TTL expired."""
        now = datetime.now()

        # Check if cache needs refresh
        if (
            self._cache_timestamp is None
            or (now - self._cache_timestamp).total_seconds() > self.cache_ttl_seconds
        ):
            # Refresh cache from settings
            # In production, this could also fetch from Redis/database
            # Settings are re-read from env vars on each refresh
            fresh_settings = get_middleware_settings()
            self._flags_cache = {
                "api_enabled": fresh_settings.api_enabled,
                "maintenance_mode": fresh_settings.maintenance_mode,
            }
            self._cache_timestamp = now

            self.logger.log_debug(
                "Feature flags cache refreshed",
                {
                    "api_enabled": self._flags_cache["api_enabled"],
                    "maintenance_mode": self._flags_cache["maintenance_mode"],
                },
            )

    def _is_api_enabled(self) -> bool:
        """Check if API is globally enabled."""
        return self._flags_cache.get("api_enabled", True)

    def _is_maintenance_mode(self) -> bool:
        """Check if API is in maintenance mode."""
        return self._flags_cache.get("maintenance_mode", False)

    def _is_endpoint_disabled(self, path: str) -> bool:
        """
        Check if specific endpoint is disabled.

        Checks for env var: DISABLE_ENDPOINT_/path/to/endpoint=true

        Args:
            path: Request path (e.g., "/api/v1/users")

        Returns:
            True if endpoint is disabled
        """
        # Convert path to env var name
        # /api/v1/users -> DISABLE_ENDPOINT_/api/v1/users
        env_key = f"DISABLE_ENDPOINT_{path}"
        is_disabled = os.getenv(env_key, "false").lower() == "true"

        return is_disabled
