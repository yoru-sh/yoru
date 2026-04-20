class EmailError(Exception):
    """
    Base exception for all email-related errors.

    Follows python.errors.rules.md BLOC-001: common base with correlation_id.
    Similar to InfrastructureError pattern in the codebase.
    """

    def __init__(self, message: str, correlation_id: str = "") -> None:
        """
        Initialize email error.

        Args:
            message: Human-readable error description
            correlation_id: Request correlation ID for tracing
        """
        self.message = message
        self.correlation_id = correlation_id
        super().__init__(self.message)


class EmailSendError(EmailError):
    """
    Raised when email sending fails after all retry attempts.

    This indicates a permanent failure - the email could not be delivered
    despite retry logic.
    """

    pass


class EmailConfigError(EmailError):
    """
    Raised when email configuration is invalid or incomplete.

    This typically occurs during initialization when required environment
    variables are missing or have invalid values.
    """

    pass


class EmailTemplateError(EmailError):
    """
    Raised when template rendering fails.

    This can occur due to:
    - Missing template file
    - Invalid template syntax
    - Missing required template variables
    """

    pass
