# Standard library
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Third-party
import aiosmtplib

# Local
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
from libs.email.exceptions import EmailSendError, EmailConfigError
from libs.email.providers.base import BaseEmailProvider, EmailMessage


class SMTPProvider(BaseEmailProvider):
    """
    SMTP email provider with timeout and retry support.

    Supports Gmail, Outlook, and any standard SMTP server.
    Follows python.async.rules.md BLOC-002 for timeout requirements.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        timeout: float = 30.0,
        logger: LoggingController | None = None,
    ) -> None:
        """
        Initialize SMTP provider.

        Args:
            host: SMTP server hostname (e.g., smtp.gmail.com)
            port: SMTP server port (usually 587 for TLS)
            username: SMTP authentication username
            password: SMTP authentication password
            use_tls: Whether to use TLS encryption
            timeout: Timeout for SMTP operations in seconds
            logger: Optional logger instance

        Raises:
            EmailConfigError: If configuration is incomplete
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout = timeout
        self.logger = logger or LoggingController(app_name="SMTPProvider")

        # BLOC-002: Validation with guard clause
        if not all([host, username, password]):
            raise EmailConfigError(
                "SMTP configuration incomplete: host, username, and password are required"
            )

    async def send(
        self,
        message: EmailMessage,
        from_email: str,
        from_name: str | None = None,
    ) -> bool:
        """
        Send email via SMTP with timeout.

        Follows python.async.rules.md BLOC-002: explicit timeout on external calls.

        Args:
            message: Email message to send
            from_email: Sender email address
            from_name: Sender display name

        Returns:
            True if sent successfully

        Raises:
            EmailSendError: If sending fails
        """
        correlation_id = get_correlation_id()
        context = {
            "operation": "send_smtp",
            "component": "SMTPProvider",
            "correlation_id": correlation_id,
            "to_email": message.to_email,
            "subject": message.subject[:50],  # Truncate for logging
            "smtp_host": self.host,
        }

        self.logger.log_info("Sending email via SMTP", context)

        try:
            # BLOC-002: Timeout obligatoire avec asyncio.timeout
            async with asyncio.timeout(self.timeout):
                # Build MIME message
                msg = MIMEMultipart("alternative")
                msg["Subject"] = message.subject
                msg["From"] = (
                    f"{from_name} <{from_email}>" if from_name else from_email
                )
                msg["To"] = message.to_email

                if message.reply_to:
                    msg["Reply-To"] = message.reply_to

                # Attach HTML body
                if message.html_body:
                    msg.attach(MIMEText(message.html_body, "html"))

                # STRONG-005: async with pour gestion ressources
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    timeout=self.timeout,
                ) as smtp:
                    if self.use_tls:
                        await smtp.starttls()
                    await smtp.login(self.username, self.password)
                    await smtp.send_message(msg)

            self.logger.log_info("SMTP email sent successfully", context)
            return True

        except asyncio.TimeoutError as e:
            # BLOC-004: Logging avant re-raise
            self.logger.log_error(
                "SMTP timeout exceeded",
                {**context, "timeout_seconds": self.timeout, "error": str(e)},
            )
            # STRONG-003: Chaîner exceptions avec from
            raise EmailSendError(
                f"SMTP timeout after {self.timeout}s to {self.host}:{self.port}",
                correlation_id,
            ) from e

        except aiosmtplib.SMTPException as e:
            # Log SMTP-specific errors
            self.logger.log_error(
                "SMTP protocol error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"SMTP send failed: {str(e)}", correlation_id
            ) from e

        except Exception as e:
            # Catch unexpected errors
            self.logger.log_error(
                "Unexpected SMTP error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"Unexpected SMTP error: {str(e)}", correlation_id
            ) from e

    async def verify_configuration(self) -> bool:
        """
        Verify SMTP configuration by attempting connection.

        Returns:
            True if connection and authentication succeed
        """
        correlation_id = get_correlation_id()
        context = {
            "operation": "verify_smtp_config",
            "component": "SMTPProvider",
            "correlation_id": correlation_id,
            "smtp_host": self.host,
            "smtp_port": self.port,
        }

        self.logger.log_info("Verifying SMTP configuration", context)

        try:
            async with asyncio.timeout(self.timeout):
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    timeout=self.timeout,
                ) as smtp:
                    if self.use_tls:
                        await smtp.starttls()
                    await smtp.login(self.username, self.password)

            self.logger.log_info("SMTP configuration verified successfully", context)
            return True

        except Exception as e:
            self.logger.log_error(
                "SMTP configuration verification failed",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            return False
