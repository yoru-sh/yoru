"""API Exceptions."""

from .domain_exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
    PermissionError,
    AuthenticationError,
    ConflictError,
    RateLimitError,
)

__all__ = [
    "DomainError",
    "NotFoundError",
    "ValidationError",
    "PermissionError",
    "AuthenticationError",
    "ConflictError",
    "RateLimitError",
]
