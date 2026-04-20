"""OpenTelemetry tracing middleware with backward-compatible correlation IDs."""

import os
from uuid import uuid4
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from libs.log_manager.controller import LoggingController


class TracingMiddleware(BaseHTTPMiddleware):
    """
    OpenTelemetry tracing middleware with backward compatibility for correlation IDs.

    Features:
    - Creates W3C trace context spans for all requests
    - Extracts distributed trace context from incoming headers
    - Maintains backward compatibility with X-Correlation-ID
    - Adds correlation_id to request.state for legacy code
    - Includes trace_id and span_id as span attributes

    The middleware ensures that:
    1. Existing code using correlation_id continues to work
    2. New tracing infrastructure provides distributed tracing
    3. Both correlation_id and trace_id are available in logs
    """

    def __init__(self, app):
        """
        Initialize tracing middleware.

        Args:
            app: FastAPI application instance
        """
        super().__init__(app)
        self.logger = LoggingController(app_name="TracingMiddleware")
        self.enabled = os.getenv("ENABLE_TRACING", "false").lower() == "true"

        # W3C trace context propagator for distributed tracing
        self.propagator = TraceContextTextMapPropagator()

        # Get tracer (may be None if tracing disabled)
        self.tracer = trace.get_tracer(__name__)

        if self.enabled:
            self.logger.log_info("Tracing middleware enabled")
        else:
            self.logger.log_debug("Tracing middleware disabled (correlation IDs only)")

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request with distributed tracing.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response with tracing headers
        """
        # Backward compatibility: correlation_id
        # Check for existing X-Correlation-ID header
        correlation_id = request.headers.get("X-Correlation-ID")

        if not correlation_id:
            # Generate new correlation ID if not provided
            correlation_id = str(uuid4())

        # Set correlation_id on request state for legacy code
        request.state.correlation_id = correlation_id

        if not self.enabled:
            # Tracing disabled - just pass through with correlation ID
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response

        # Extract distributed trace context from incoming headers
        ctx = self.propagator.extract(request.headers)

        # Create span for this request
        with self.tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            context=ctx,
            kind=trace.SpanKind.SERVER,
        ) as span:
            # Add span attributes
            span.set_attribute("correlation.id", correlation_id)
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.scheme", request.url.scheme)
            span.set_attribute("http.host", request.url.hostname or "")
            span.set_attribute("http.target", request.url.path)

            # Add client information if available
            if request.client:
                span.set_attribute("http.client_ip", request.client.host)

            # Add user_id if available (set by previous middleware)
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                span.set_attribute("user.id", user_id)

            # Add organization_id if available
            organization_id = getattr(request.state, "organization_id", None)
            if organization_id:
                span.set_attribute("organization.id", organization_id)

            try:
                # Process request
                response = await call_next(request)

                # Add response attributes
                span.set_attribute("http.status_code", response.status_code)

                # Set span status based on HTTP status code
                if response.status_code >= 500:
                    span.set_status(
                        trace.Status(
                            trace.StatusCode.ERROR,
                            f"HTTP {response.status_code}"
                        )
                    )
                else:
                    span.set_status(trace.Status(trace.StatusCode.OK))

                # Add correlation ID to response headers (backward compatibility)
                response.headers["X-Correlation-ID"] = correlation_id

                # Add trace context to response headers for debugging
                span_context = span.get_span_context()
                if span_context.is_valid:
                    response.headers["X-Trace-ID"] = format(
                        span_context.trace_id, '032x'
                    )
                    response.headers["X-Span-ID"] = format(
                        span_context.span_id, '016x'
                    )

                return response

            except Exception as e:
                # Record exception in span
                span.set_status(
                    trace.Status(trace.StatusCode.ERROR, str(e))
                )
                span.record_exception(e)

                # Log error
                self.logger.log_error(
                    f"Request failed: {str(e)}",
                    {
                        "correlation_id": correlation_id,
                        "path": request.url.path,
                        "method": request.method,
                    }
                )

                # Re-raise exception
                raise
