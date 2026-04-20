# Third-party
import httpx

# Local
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
from libs.email.exceptions import EmailSendError, EmailConfigError
from libs.email.providers.base import BaseEmailProvider, EmailMessage


class SendGridProvider(BaseEmailProvider):
    """
    SendGrid transactional email provider.

    Uses SendGrid's HTTP API for reliable, scalable email delivery.
    Ideal for production environments with high volume.
    """

    API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        logger: LoggingController | None = None,
    ) -> None:
        """
        Initialize SendGrid provider.

        Args:
            api_key: SendGrid API key (starts with SG.)
            timeout: Timeout for API calls in seconds
            logger: Optional logger instance

        Raises:
            EmailConfigError: If API key is missing or invalid
        """
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logger or LoggingController(app_name="SendGridProvider")

        # BLOC-002: Validation with guard clause
        if not api_key:
            raise EmailConfigError("SendGrid API key is required")

        if not api_key.startswith("SG."):
            self.logger.log_warning(
                "SendGrid API key should start with 'SG.'",
                {"api_key_prefix": api_key[:5] if len(api_key) >= 5 else api_key},
            )

    async def send(
        self,
        message: EmailMessage,
        from_email: str,
        from_name: str | None = None,
    ) -> bool:
        """
        Send email via SendGrid API.

        Follows python.async.rules.md BLOC-002: explicit timeout on HTTP calls.

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
            "operation": "send_sendgrid",
            "component": "SendGridProvider",
            "correlation_id": correlation_id,
            "to_email": message.to_email,
            "subject": message.subject[:50],
        }

        self.logger.log_info("Sending email via SendGrid", context)

        # Build SendGrid API payload
        payload = {
            "personalizations": [
                {
                    "to": [{"email": message.to_email}],
                    "subject": message.subject,
                }
            ],
            "from": {
                "email": from_email,
                "name": from_name or from_email,
            },
            "content": [
                {
                    "type": "text/html",
                    "value": message.html_body,
                }
            ],
        }

        # Add to_name if provided
        if message.to_name:
            payload["personalizations"][0]["to"][0]["name"] = message.to_name

        # Add reply_to if provided
        if message.reply_to:
            payload["reply_to"] = {"email": message.reply_to}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # STRONG-004: Use httpx.AsyncClient for async HTTP
            # BLOC-002: Timeout obligatoire
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.API_URL,
                    json=payload,
                    headers=headers,
                )

                # SendGrid returns 202 Accepted on success
                if response.status_code == 202:
                    self.logger.log_info(
                        "SendGrid email sent successfully",
                        {**context, "status_code": response.status_code},
                    )
                    return True
                else:
                    # Log error details from SendGrid
                    error_detail = response.text
                    self.logger.log_error(
                        "SendGrid API error",
                        {
                            **context,
                            "status_code": response.status_code,
                            "error": error_detail,
                        },
                    )
                    raise EmailSendError(
                        f"SendGrid API error: {response.status_code} - {error_detail}",
                        correlation_id,
                    )

        except httpx.TimeoutException as e:
            # BLOC-004: Logging before re-raise
            self.logger.log_error(
                "SendGrid API timeout",
                {**context, "timeout_seconds": self.timeout, "error": str(e)},
            )
            # STRONG-003: Chain exceptions
            raise EmailSendError(
                f"SendGrid timeout after {self.timeout}s",
                correlation_id,
            ) from e

        except httpx.HTTPError as e:
            self.logger.log_error(
                "SendGrid HTTP error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"SendGrid HTTP error: {str(e)}",
                correlation_id,
            ) from e

        except Exception as e:
            self.logger.log_error(
                "Unexpected SendGrid error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"Unexpected SendGrid error: {str(e)}",
                correlation_id,
            ) from e

    async def verify_configuration(self) -> bool:
        """
        Verify SendGrid API key by making a test request.

        Returns:
            True if API key is valid
        """
        correlation_id = get_correlation_id()
        context = {
            "operation": "verify_sendgrid_config",
            "component": "SendGridProvider",
            "correlation_id": correlation_id,
        }

        self.logger.log_info("Verifying SendGrid configuration", context)

        # Use SendGrid's /scopes endpoint to verify API key
        verify_url = "https://api.sendgrid.com/v3/scopes"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(verify_url, headers=headers)

                if response.status_code == 200:
                    self.logger.log_info(
                        "SendGrid configuration verified successfully",
                        context,
                    )
                    return True
                else:
                    self.logger.log_error(
                        "SendGrid configuration verification failed",
                        {
                            **context,
                            "status_code": response.status_code,
                            "error": response.text,
                        },
                    )
                    return False

        except Exception as e:
            self.logger.log_error(
                "SendGrid configuration verification error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            return False
