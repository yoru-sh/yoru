# Standard library
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmailMessage:
    """
    Represents an email message to be sent.

    This is the universal format used by all providers.
    """

    to_email: str
    subject: str
    html_body: str
    to_name: str | None = None
    reply_to: str | None = None


class BaseEmailProvider(ABC):
    """
    Abstract base class for email providers.

    All providers (SMTP, SendGrid, Resend) must implement this interface
    to ensure consistent behavior across different email backends.
    """

    @abstractmethod
    async def send(
        self,
        message: EmailMessage,
        from_email: str,
        from_name: str | None = None,
    ) -> bool:
        """
        Send an email message.

        Args:
            message: The email message to send
            from_email: Sender email address
            from_name: Sender display name (optional)

        Returns:
            True if sent successfully

        Raises:
            EmailSendError: If sending fails after retries
        """
        pass

    @abstractmethod
    async def verify_configuration(self) -> bool:
        """
        Verify provider configuration is valid.

        Returns:
            True if configuration is valid and connection works
        """
        pass
