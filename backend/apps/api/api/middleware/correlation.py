"""Correlation ID middleware for request tracing."""

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates or extracts correlation IDs for request tracing.

    - Extracts X-Correlation-ID from incoming request headers if present
    - Generates a new UUID if no correlation ID is provided
    - Stores the correlation ID in request.state.correlation_id
    - Adds X-Correlation-ID header to the response
    """

    async def dispatch(self, request: Request, call_next):
        # Extract from header or generate new correlation ID
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())

        # Store in request state for downstream access
        request.state.correlation_id = correlation_id

        # Process the request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response
