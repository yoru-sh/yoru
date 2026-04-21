"""Polar billing webhook handler with HMAC verify + event idempotency.

Contract: wave-20-C C1 task brief. BILLING-WEBHOOK-SECURITY.md describes a
Stripe-format `t=<ts>,v1=<hex>` scheme; this v0 follows the simpler direct-hex
scheme mandated by the brief (`X-Polar-Signature: <hex-sha256>`).

Flow:
  1. `POLAR_WEBHOOK_SECRET` unset → 503.
  2. Read raw body + X-Polar-Signature; verify via hmac.compare_digest. Any
     mismatch or missing header → 400 (logged as `signature_mismatch`).
  3. Parse JSON AFTER signature passes. Extract `id`, `type`, `data`.
  4. Handled types only: checkout.completed | subscription.updated |
     subscription.cancelled. Unknown → 200 no-op, no DB mutation.
  5. Idempotency: PK-hit on `billing_events.event_id` → 200 short-circuit.
  6. Apply org mutation + INSERT billing_events row in one transaction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import Session as DBSession

from apps.api.api.routers.receipt.db import engine
from apps.api.api.routers.receipt.deps import _naive_utc_now

from .models import BillingEvent, Org

_logger = logging.getLogger(__name__)

_SIGNATURE_HEADER = "x-polar-signature"  # Starlette lowercases header keys
_VALID_PLANS = {"team", "org"}
_HANDLED_TYPES = {
    "checkout.completed",
    "subscription.created",
    "subscription.updated",
    "subscription.cancelled",
}


class WebhookRouter:
    """Polar billing webhook receiver (same class-idiom as AuthRouter)."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["billing:webhook"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post("/webhook")(self.receive_webhook)

    async def receive_webhook(self, request: Request) -> dict[str, Any]:
        secret = os.environ.get("POLAR_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook secret not configured.",
            )

        body = await request.body()
        received_sig = (request.headers.get(_SIGNATURE_HEADER) or "").strip()
        if not received_sig:
            _logger.warning("signature_mismatch reason=missing_header")
            raise HTTPException(status_code=400, detail="Missing signature header.")

        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_sig):
            _logger.warning("signature_mismatch reason=digest_mismatch")
            raise HTTPException(status_code=400, detail="Invalid signature.")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON body.")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON envelope.")

        event_id = payload.get("id")
        event_type = payload.get("type")
        data = payload.get("data") or {}
        if not isinstance(event_id, str) or not event_id:
            raise HTTPException(status_code=400, detail="Missing or invalid 'id'.")
        if not isinstance(event_type, str) or not event_type:
            raise HTTPException(status_code=400, detail="Missing or invalid 'type'.")
        if not isinstance(data, dict):
            data = {}

        # Unknown event types: 200 no-op, zero DB touch (AC #8).
        if event_type not in _HANDLED_TYPES:
            return {"status": "processed", "event_id": event_id}

        with DBSession(engine) as db:
            if db.get(BillingEvent, event_id) is not None:
                # Idempotent replay — no mutation, no new ledger row.
                return {"status": "processed", "event_id": event_id}

            org_id = self._apply_mutation(db, event_type, data)

            db.add(
                BillingEvent(
                    event_id=event_id,
                    processed_at=_naive_utc_now(),
                    org_id=org_id,
                    event_type=event_type,
                )
            )
            db.commit()

        return {"status": "processed", "event_id": event_id}

    def _apply_mutation(
        self,
        db: DBSession,
        event_type: str,
        data: dict[str, Any],
    ) -> Optional[str]:
        if event_type == "checkout.completed":
            org_id = data.get("client_reference_id")
            plan = data.get("plan")
            if not isinstance(org_id, str) or not org_id:
                raise HTTPException(
                    status_code=400,
                    detail="checkout.completed missing client_reference_id.",
                )
            if plan not in _VALID_PLANS:
                raise HTTPException(
                    status_code=400,
                    detail=f"checkout.completed has invalid plan (got {plan!r}).",
                )
            org = db.get(Org, org_id)
            if org is None:
                # US-18 invite flow will provision Orgs — for v0 the webhook is
                # the upstream-authoritative source, so upsert keeps AC #3 green.
                db.add(Org(id=org_id, plan=plan))
            else:
                org.plan = plan
                db.add(org)
            return org_id

        if event_type == "subscription.created":
            org_id = data.get("client_reference_id")
            plan = data.get("plan")
            if not isinstance(org_id, str) or not org_id:
                raise HTTPException(
                    status_code=400,
                    detail="subscription.created missing client_reference_id.",
                )
            if plan not in _VALID_PLANS:
                raise HTTPException(
                    status_code=400,
                    detail=f"subscription.created has invalid plan (got {plan!r}).",
                )
            org = db.get(Org, org_id)
            if org is None:
                db.add(Org(id=org_id, plan=plan))
            else:
                org.plan = plan
                db.add(org)
            _logger.info("billing.tier_upgraded org=%s plan=%s", org_id, plan)
            return org_id

        if event_type == "subscription.updated":
            org_id = data.get("client_reference_id")
            seat_count = data.get("seat_count")
            if isinstance(org_id, str) and org_id and seat_count is not None:
                org = db.get(Org, org_id)
                if org is not None:
                    try:
                        org.seat_count = int(seat_count)
                        db.add(org)
                    except (TypeError, ValueError):
                        pass
            return org_id if isinstance(org_id, str) else None

        if event_type == "subscription.cancelled":
            org_id = data.get("client_reference_id")
            if isinstance(org_id, str) and org_id:
                org = db.get(Org, org_id)
                if org is not None:
                    org.plan = "free"
                    parsed = _parse_dt(data.get("current_period_end"))
                    if parsed is not None:
                        org.plan_downgrades_at = parsed
                    db.add(org)
            return org_id if isinstance(org_id, str) else None

        return None


def _parse_dt(raw: Any) -> Optional[datetime]:
    """Parse ISO-8601 string or unix seconds into naive UTC; None on failure."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    return None
