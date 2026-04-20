# Standard library
import os
from dataclasses import dataclass

# Local
from libs.email.exceptions import EmailConfigError


@dataclass
class EmailConfig:
    """Configuration for email service following RedisManager pattern."""

    provider: str  # smtp, sendgrid, resend
    from_email: str
    from_name: str
    brand_name: str
    support_email: str
    company_address: str
    retry_attempts: int
    timeout: float

    # SMTP settings
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True

    # SendGrid settings
    sendgrid_api_key: str | None = None

    # Resend settings
    resend_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "EmailConfig":
        """
        Create EmailConfig from environment variables.

        Follows libs/redis pattern for ENV-based initialization.

        Raises:
            EmailConfigError: If required variables are missing.
        """
        provider = os.getenv("EMAIL_PROVIDER", "smtp")
        from_email = os.getenv("SMTP_FROM_EMAIL", "")
        from_name = os.getenv("SMTP_FROM_NAME", "")

        # Validate required fields
        if not from_email:
            raise EmailConfigError(
                "EMAIL_FROM_EMAIL or SMTP_FROM_EMAIL environment variable is required"
            )

        # Provider-specific validation
        if provider == "smtp":
            smtp_host = os.getenv("SMTP_HOST")
            smtp_username = os.getenv("SMTP_USERNAME")
            smtp_password = os.getenv("SMTP_PASSWORD")

            if not all([smtp_host, smtp_username, smtp_password]):
                raise EmailConfigError(
                    "SMTP provider requires SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD"
                )

        elif provider == "sendgrid":
            sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
            if not sendgrid_api_key:
                raise EmailConfigError("SendGrid provider requires SENDGRID_API_KEY")

        elif provider == "resend":
            resend_api_key = os.getenv("RESEND_API_KEY")
            if not resend_api_key:
                raise EmailConfigError("Resend provider requires RESEND_API_KEY")

        return cls(
            provider=provider,
            from_email=from_email,
            from_name=from_name,
            brand_name=os.getenv("EMAIL_BRAND_NAME", "SaaSForge"),
            support_email=os.getenv("EMAIL_SUPPORT_EMAIL", from_email),
            company_address=os.getenv("EMAIL_COMPANY_ADDRESS", ""),
            retry_attempts=int(os.getenv("EMAIL_RETRY_ATTEMPTS", "3")),
            timeout=float(os.getenv("EMAIL_TIMEOUT", "30.0")),
            # SMTP
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            # SendGrid
            sendgrid_api_key=os.getenv("SENDGRID_API_KEY"),
            # Resend
            resend_api_key=os.getenv("RESEND_API_KEY"),
        )
