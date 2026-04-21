"""Welcome-email sender (wave-54 ACTIVATION Hour-0).

Stub-first delivery: when `SMTP_HOST` is unset we log the rendered body
to stdout/stderr via the standard logger so the welcome event is never
lost (the dashboard cron / log scraper can replay if needed). When
`SMTP_HOST` is set we open an `smtplib.SMTP` connection and ship the
message for real. Idempotency is enforced by the caller (the
`/auth/welcome-email` endpoint dedupes via the `users.welcome_email_sent_at`
column); this module is a pure side-effect renderer/sender.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).with_name("templates") / "welcome.txt"

_logger = logging.getLogger(__name__)


def _render(user_email: str) -> tuple[str, str]:
    """Read the template and substitute placeholders.

    Returns (subject, body). The template's first line is `Subject: …`,
    everything from the blank line onward is the body — same convention
    as PASSWORD_RESET_EMAIL_TEMPLATE in auth_router.py so future digest
    templates can share a renderer.
    """
    raw = _TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = raw.replace("{{user_email}}", user_email)
    subject_line, _, body = rendered.partition("\n\n")
    subject = subject_line.removeprefix("Subject:").strip()
    return subject, body


def send_welcome_email(user_email: str) -> None:
    """Render and dispatch the welcome email.

    - `SMTP_HOST` unset (default in dev/test): log the rendered body so
      no signup ever silently drops a welcome event.
    - `SMTP_HOST` set: open `smtplib.SMTP(host, port)`, optional
      STARTTLS + login when `SMTP_USERNAME`/`SMTP_PASSWORD` provided,
      then send.
    """
    subject, body = _render(user_email)
    smtp_host = os.getenv("SMTP_HOST")

    if not smtp_host:
        _logger.info(
            "[WELCOME-EMAIL-STUB] to=%s subject=%s body=%s",
            user_email,
            subject,
            body,
        )
        return

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "noreply@receipt.sh")
    msg["To"] = user_email
    msg["Subject"] = subject
    msg.set_content(body)

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes"):
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
