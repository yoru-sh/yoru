"""Request timeout middleware."""

import asyncio

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.api.api.config.middleware_settings import get_middleware_settings
from libs.log_manager.controller import LoggingController


class TimeoutMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces request timeout.

    Features:
    - Configurable timeout per request
    - Returns 504 Gateway Timeout on timeout
    - Logs timeout events with correlation ID
    - Prevents zombie requests from consuming resources

    This middleware should be placed early in the stack (after tracing/logging)
    to ensure all downstream processing respects the timeout.

    Configuration:
    - REQUEST_TIMEOUT_SECONDS: Global timeout in seconds (default: 30)

    Compliance:
    - python.state.rules.md BLOC-002: Settings via pydantic-settings
    """

    def __init__(self, app, timeout_seconds: int | None = None):
        """
        Initialize timeout middleware.

        Args:
            app: FastAPI application instance
            timeout_seconds: Timeout in seconds (default: from MiddlewareSettings or 30)
        """
        super().__init__(app)
        self.logger = LoggingController(app_name="TimeoutMiddleware")

        # Get timeout from settings or parameter
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            settings = get_middleware_settings()
            self.timeout_seconds = settings.request_timeout_seconds

        self.logger.log_info(
            f"Request timeout middleware enabled ({self.timeout_seconds}s)"
        )

    async def dispatch(self, request: Request, call_next):
        """
        Process request with timeout enforcement.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response or 504 on timeout
        """
        correlation_id = getattr(request.state, "correlation_id", "")

        try:
            # Wrap request processing in timeout
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds
            )
            return response

        except asyncio.TimeoutError:
            # Request exceeded timeout
            self.logger.log_error(
                "Request timeout exceeded",
                {
                    "correlation_id": correlation_id,
                    "timeout_seconds": self.timeout_seconds,
                    "method": request.method,
                    "path": request.url.path,
                },
            )

            return JSONResponse(
                status_code=504,
                content={
                    "error": "request_timeout",
                    "message": f"Request exceeded timeout of {self.timeout_seconds} seconds",
                    "correlation_id": correlation_id,
                },
                headers={
                    "X-Correlation-ID": correlation_id,
                }
            )

        except Exception as e:
            # Other errors should be handled by exception middleware
            raise
