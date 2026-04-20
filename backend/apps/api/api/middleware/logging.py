"""Request logging middleware."""

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from libs.log_manager.controller import LoggingController


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all HTTP requests with timing and context.

    Logs:
    - Request start: method, path, client IP
    - Request end: status code, duration in milliseconds
    - Correlation ID for distributed tracing
    """

    def __init__(self, app):
        super().__init__(app)
        self.logger = LoggingController(app_name="RequestLogger")

    async def dispatch(self, request: Request, call_next):
        # Get correlation ID from request state (set by CorrelationMiddleware)
        correlation_id = getattr(request.state, "correlation_id", "")
        start_time = time.time()

        context = {
            "operation": "http_request",
            "component": "RequestLoggingMiddleware",
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else None,
        }

        self.logger.log_info("Request started", context)

        # Process the request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        self.logger.log_info(
            "Request completed",
            {
                **context,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return response
