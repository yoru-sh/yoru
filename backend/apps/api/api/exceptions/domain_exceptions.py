"""Domain exceptions for the API.

Custom exception hierarchy for domain-specific errors.
These exceptions are caught by the global exception handler
and converted to appropriate HTTP responses.
"""


class DomainError(Exception):
    """Base class for all domain exceptions."""

    def __init__(self, message: str, correlation_id: str = ""):
        self.message = message
        self.correlation_id = correlation_id
        super().__init__(self.message)


class NotFoundError(DomainError):
    """Raised when a requested resource is not found."""

    pass


class ValidationError(DomainError):
    """Raised when input validation fails."""

    pass


class PermissionError(DomainError):
    """Raised when the user lacks permission to perform an action."""

    pass


class AuthenticationError(DomainError):
    """Raised when authentication fails or is required."""

    pass


class ConflictError(DomainError):
    """Raised when an operation conflicts with existing state."""

    pass


class RateLimitError(DomainError):
    """Raised when rate limits are exceeded."""

    pass
