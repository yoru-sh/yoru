"""OpenTelemetry tracer initialization and configuration."""

import os
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from libs.log_manager.controller import LoggingController


def init_tracer(service_name: str = "saas-api") -> Optional[trace.Tracer]:
    """
    Initialize OpenTelemetry tracer with configured exporter.

    Supports both Jaeger and OTLP exporters based on configuration.
    Automatically instruments FastAPI, httpx, and Redis when enabled.

    Args:
        service_name: Name of the service (default: "saas-api")

    Returns:
        Tracer instance if enabled, None otherwise

    Environment Variables:
        ENABLE_TRACING: Enable/disable tracing (default: false)
        OTEL_EXPORTER_TYPE: Exporter type - "jaeger" or "otlp" (default: jaeger)
        OTEL_SERVICE_NAME: Service name override
        OTEL_SAMPLING_RATE: Sampling rate 0.0-1.0 (default: 1.0)
        JAEGER_AGENT_HOST: Jaeger agent hostname (default: localhost)
        JAEGER_AGENT_PORT: Jaeger agent port (default: 6831)
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4317)

    Example:
        >>> from libs.tracing.tracer import init_tracer
        >>> tracer = init_tracer("my-service")
        >>> if tracer:
        ...     with tracer.start_as_current_span("operation"):
        ...         # Your code here
        ...         pass
    """
    logger = LoggingController(app_name="TracingManager")

    # Check if tracing is enabled
    enabled = os.getenv("ENABLE_TRACING", "false").lower() == "true"

    if not enabled:
        logger.log_info("Distributed tracing disabled")
        return None

    try:
        # Override service name from env if provided
        service_name = os.getenv("OTEL_SERVICE_NAME", service_name)

        # Create resource with service information
        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv("APP_VERSION", "1.0.0"),
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })

        # Create tracer provider
        provider = TracerProvider(resource=resource)

        # Configure exporter based on type
        exporter_type = os.getenv("OTEL_EXPORTER_TYPE", "jaeger").lower()

        if exporter_type == "jaeger":
            # Jaeger exporter configuration
            jaeger_host = os.getenv("JAEGER_AGENT_HOST", "localhost")
            jaeger_port = int(os.getenv("JAEGER_AGENT_PORT", "6831"))

            exporter = JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=jaeger_port,
            )

            logger.log_info(
                "Jaeger exporter configured",
                {"host": jaeger_host, "port": jaeger_port}
            )

        elif exporter_type == "otlp":
            # OTLP exporter configuration
            otlp_endpoint = os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://localhost:4317"
            )

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)

            logger.log_info(
                "OTLP exporter configured",
                {"endpoint": otlp_endpoint}
            )

        else:
            logger.log_error(
                f"Unknown OTEL exporter type: {exporter_type}",
                {"exporter_type": exporter_type}
            )
            return None

        # Add batch span processor
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(provider)

        logger.log_info(
            "OpenTelemetry tracing initialized",
            {
                "service_name": service_name,
                "exporter_type": exporter_type,
                "sampling_rate": os.getenv("OTEL_SAMPLING_RATE", "1.0"),
            }
        )

        # Return tracer instance
        return trace.get_tracer(__name__)

    except Exception as e:
        logger.log_error(
            "Failed to initialize OpenTelemetry tracing",
            {"error": str(e)}
        )
        return None


def instrument_fastapi(app):
    """
    Auto-instrument FastAPI application for tracing.

    Adds automatic span creation for all HTTP requests.

    Args:
        app: FastAPI application instance
    """
    if os.getenv("ENABLE_TRACING", "false").lower() != "true":
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)

        logger = LoggingController(app_name="TracingManager")
        logger.log_info("FastAPI instrumented for tracing")

    except Exception as e:
        logger = LoggingController(app_name="TracingManager")
        logger.log_warning(
            "Failed to instrument FastAPI",
            {"error": str(e)}
        )


def instrument_httpx():
    """
    Auto-instrument httpx client for tracing.

    Adds automatic span creation for all HTTP client requests.
    """
    if os.getenv("ENABLE_TRACING", "false").lower() != "true":
        return

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()

        logger = LoggingController(app_name="TracingManager")
        logger.log_info("HTTPX client instrumented for tracing")

    except Exception as e:
        logger = LoggingController(app_name="TracingManager")
        logger.log_warning(
            "Failed to instrument HTTPX",
            {"error": str(e)}
        )


def instrument_redis():
    """
    Auto-instrument Redis client for tracing.

    Adds automatic span creation for all Redis operations.
    """
    if os.getenv("ENABLE_TRACING", "false").lower() != "true":
        return

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()

        logger = LoggingController(app_name="TracingManager")
        logger.log_info("Redis client instrumented for tracing")

    except Exception as e:
        logger = LoggingController(app_name="TracingManager")
        logger.log_warning(
            "Failed to instrument Redis",
            {"error": str(e)}
        )
