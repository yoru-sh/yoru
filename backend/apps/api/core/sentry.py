"""Sentry error-capture — DSN-gated, no-op by default.

Keeps the base install slim: `sentry-sdk[fastapi]` lives in the
`observability` extra (`uv sync --extra observability`). When the extra is
not installed OR `SENTRY_DSN` is unset, `init_sentry()` returns False and
does nothing — no network, no side effects, no import failure.

Policy: audit-grade product. Request bodies and cookies are dropped in
`before_send` and `max_request_body_size="never"` is set. PII off
(`send_default_pii=False`).
"""
from __future__ import annotations

import os
from typing import Any


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set. Returns True if initialized."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ImportError:
        return False
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_drop_bodies,
        integrations=[FastApiIntegration()],
    )
    return True


def _drop_bodies(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    req = event.get("request") or {}
    req.pop("data", None)
    req.pop("cookies", None)
    return event
