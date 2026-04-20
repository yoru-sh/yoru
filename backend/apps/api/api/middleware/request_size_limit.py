"""Request size limit middleware."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.api.api.config.middleware_settings import get_middleware_settings
from libs.log_manager.controller import LoggingController


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces maximum request body size.

    Features:
    - Checks Content-Length header before reading body
    - Returns 413 Payload Too Large if limit exceeded
    - Prevents resource exhaustion from large payloads
    - Logs violations with correlation ID

    This middleware should be placed very early in the stack (before logging)
    to avoid logging large payloads and wasting resources.

    Configuration:
    - MAX_REQUEST_SIZE_MB: Maximum request size in MB (default: 10)

    Compliance:
    - python.state.rules.md BLOC-002: Settings via pydantic-settings
    """

    def __init__(self, app, max_size_mb: int | None = None):
        """
        Initialize request size limit middleware.

        Args:
            app: FastAPI application instance
            max_size_mb: Maximum request size in MB (default: from MiddlewareSettings or 10)
        """
        super().__init__(app)
        self.logger = LoggingController(app_name="RequestSizeLimitMiddleware")

        # Get max size from settings or parameter
        if max_size_mb is not None:
            self.max_size_mb = max_size_mb
        else:
            settings = get_middleware_settings()
            self.max_size_mb = settings.max_request_size_mb

        # Convert to bytes for comparison
        self.max_size_bytes = self.max_size_mb * 1024 * 1024

        self.logger.log_info(
            f"Request size limit middleware enabled ({self.max_size_mb}MB max)"
        )

    async def dispatch(self, request: Request, call_next):
        """
        Process request with size limit enforcement.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response or 413 if payload too large
        """
        # Check Content-Length header if present
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                content_length_bytes = int(content_length)

                if content_length_bytes > self.max_size_bytes:
                    # Payload too large
                    correlation_id = getattr(request.state, "correlation_id", "")

                    self.logger.log_warning(
                        "Request payload too large",
                        {
                            "correlation_id": correlation_id,
                            "content_length_mb": round(content_length_bytes / 1024 / 1024, 2),
                            "max_size_mb": self.max_size_mb,
                            "method": request.method,
                            "path": request.url.path,
                        },
                    )

                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "payload_too_large",
                            "message": f"Request payload exceeds maximum size of {self.max_size_mb}MB",
                            "max_size_mb": self.max_size_mb,
                            "received_size_mb": round(content_length_bytes / 1024 / 1024, 2),
                        },
                    )

            except ValueError:
                # Invalid Content-Length header, let it through
                # Will be caught by FastAPI if malformed
                pass

        # Size is acceptable or not specified, continue processing
        return await call_next(request)
