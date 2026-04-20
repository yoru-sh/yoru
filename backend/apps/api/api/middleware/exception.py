"""Global exception handler middleware."""

from fastapi import Request
from fastapi.responses import JSONResponse

from libs.log_manager.controller import LoggingController
from apps.api.api.exceptions.domain_exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
    AuthenticationError,
    PermissionError as DomainPermissionError,
)

logger = LoggingController(app_name="ExceptionHandler")


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler that converts exceptions to JSON responses.

    Maps domain exceptions to appropriate HTTP status codes:
    - NotFoundError -> 404
    - ValidationError -> 400
    - AuthenticationError -> 401
    - PermissionError -> 403
    - Other exceptions -> 500
    """
    correlation_id = getattr(request.state, "correlation_id", "")

    context = {
        "operation": "exception_handler",
        "component": "GlobalExceptionHandler",
        "correlation_id": correlation_id,
        "path": request.url.path,
        "method": request.method,
    }

    # Handle NotFoundError
    if isinstance(exc, NotFoundError):
        logger.log_warning("Resource not found", context)
        return JSONResponse(
            status_code=404,
            content={"detail": exc.message, "correlation_id": correlation_id},
        )

    # Handle ValidationError
    if isinstance(exc, ValidationError):
        logger.log_warning("Validation error", context)
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message, "correlation_id": correlation_id},
        )

    # Handle AuthenticationError
    if isinstance(exc, AuthenticationError):
        logger.log_warning("Authentication error", context)
        return JSONResponse(
            status_code=401,
            content={"detail": exc.message, "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Handle PermissionError
    if isinstance(exc, DomainPermissionError):
        logger.log_warning("Permission error", context)
        return JSONResponse(
            status_code=403,
            content={"detail": exc.message, "correlation_id": correlation_id},
        )

    # Handle other DomainErrors
    if isinstance(exc, DomainError):
        logger.log_error("Domain error", {**context, "error": str(exc)})
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message, "correlation_id": correlation_id},
        )

    # Handle unhandled exceptions
    logger.log_exception(exc, context)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "correlation_id": correlation_id},
    )
