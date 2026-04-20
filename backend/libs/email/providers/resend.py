# Third-party
import httpx

# Local
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id
from libs.email.exceptions import EmailSendError, EmailConfigError
from libs.email.providers.base import BaseEmailProvider, EmailMessage


class ResendProvider(BaseEmailProvider):
    """
    Resend transactional email provider.

    Modern, developer-friendly transactional email service.
    Simple API, great for SaaS applications.
    """

    API_URL = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        logger: LoggingController | None = None,
    ) -> None:
        """
        Initialize Resend provider.

        Args:
            api_key: Resend API key (starts with re_)
            timeout: Timeout for API calls in seconds
            logger: Optional logger instance

        Raises:
            EmailConfigError: If API key is missing or invalid
        """
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logger or LoggingController(app_name="ResendProvider")

        # BLOC-002: Validation with guard clause
        if not api_key:
            raise EmailConfigError("Resend API key is required")

        if not api_key.startswith("re_"):
            self.logger.log_warning(
                "Resend API key should start with 're_'",
                {"api_key_prefix": api_key[:5] if len(api_key) >= 5 else api_key},
            )

    async def send(
        self,
        message: EmailMessage,
        from_email: str,
        from_name: str | None = None,
    ) -> bool:
        """
        Send email via Resend API.

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
            "operation": "send_resend",
            "component": "ResendProvider",
            "correlation_id": correlation_id,
            "to_email": message.to_email,
            "subject": message.subject[:50],
        }

        self.logger.log_info("Sending email via Resend", context)

        # Build Resend API payload
        from_field = f"{from_name} <{from_email}>" if from_name else from_email

        payload = {
            "from": from_field,
            "to": [message.to_email],
            "subject": message.subject,
            "html": message.html_body,
        }

        # Add reply_to if provided
        if message.reply_to:
            payload["reply_to"] = message.reply_to

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

                # Resend returns 200 OK on success
                if response.status_code == 200:
                    response_data = response.json()
                    email_id = response_data.get("id", "unknown")

                    self.logger.log_info(
                        "Resend email sent successfully",
                        {
                            **context,
                            "status_code": response.status_code,
                            "email_id": email_id,
                        },
                    )
                    return True
                else:
                    # Log error details from Resend
                    error_detail = response.text
                    self.logger.log_error(
                        "Resend API error",
                        {
                            **context,
                            "status_code": response.status_code,
                            "error": error_detail,
                        },
                    )
                    raise EmailSendError(
                        f"Resend API error: {response.status_code} - {error_detail}",
                        correlation_id,
                    )

        except httpx.TimeoutException as e:
            # BLOC-004: Logging before re-raise
            self.logger.log_error(
                "Resend API timeout",
                {**context, "timeout_seconds": self.timeout, "error": str(e)},
            )
            # STRONG-003: Chain exceptions
            raise EmailSendError(
                f"Resend timeout after {self.timeout}s",
                correlation_id,
            ) from e

        except httpx.HTTPError as e:
            self.logger.log_error(
                "Resend HTTP error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"Resend HTTP error: {str(e)}",
                correlation_id,
            ) from e

        except Exception as e:
            self.logger.log_error(
                "Unexpected Resend error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            raise EmailSendError(
                f"Unexpected Resend error: {str(e)}",
                correlation_id,
            ) from e

    async def verify_configuration(self) -> bool:
        """
        Verify Resend API key by making a test request.

        Returns:
            True if API key is valid
        """
        correlation_id = get_correlation_id()
        context = {
            "operation": "verify_resend_config",
            "component": "ResendProvider",
            "correlation_id": correlation_id,
        }

        self.logger.log_info("Verifying Resend configuration", context)

        # Use Resend's /api-keys endpoint to verify
        verify_url = "https://api.resend.com/api-keys"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(verify_url, headers=headers)

                if response.status_code == 200:
                    self.logger.log_info(
                        "Resend configuration verified successfully",
                        context,
                    )
                    return True
                else:
                    self.logger.log_error(
                        "Resend configuration verification failed",
                        {
                            **context,
                            "status_code": response.status_code,
                            "error": response.text,
                        },
                    )
                    return False

        except Exception as e:
            self.logger.log_error(
                "Resend configuration verification error",
                {**context, "error": str(e), "error_type": type(e).__name__},
            )
            return False
