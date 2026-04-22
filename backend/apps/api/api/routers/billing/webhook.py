"""Stripe billing webhook — signature verify + Supabase subscription upsert.

Stripe POSTs events to `/api/v1/billing/webhook` with header
`Stripe-Signature: t=<ts>,v1=<hex>`. The stripe SDK's
`Webhook.construct_event()` handles verify + parse; on success we call
the `set_user_subscription_from_polar` / `cancel_user_subscription_from_polar`
RPCs on Supabase (names kept for migration-history stability — they're
provider-agnostic underneath).

Flow:
  1. `STRIPE_WEBHOOK_SECRET` unset → 503.
  2. `construct_event` verifies signature + parses envelope.
  3. Handled types: checkout.session.completed | customer.subscription.created
     | customer.subscription.updated | customer.subscription.deleted.
     Unknown → 200 no-op.
  4. Idempotency: PK-hit on `billing_events.event_id` (SQLite ledger) →
     200 short-circuit.
  5. Apply Supabase mutation via RPC + INSERT billing_events row.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import Session as DBSession

from apps.api.api.routers.receipt.db import engine
from apps.api.api.routers.receipt.deps import _naive_utc_now

from .models import BillingEvent

_logger = logging.getLogger(__name__)

_VALID_PLANS = {"pro", "team", "org"}
_HANDLED_TYPES = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "")


def _call_supabase_rpc(fn: str, args: dict[str, Any]) -> None:
    """Fire a SECURITY DEFINER RPC on Supabase. Raises on non-2xx."""
    if not _SUPABASE_URL or not _SUPABASE_ANON:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY missing")
    resp = httpx.post(
        f"{_SUPABASE_URL}/rest/v1/rpc/{fn}",
        headers={
            "apikey": _SUPABASE_ANON,
            "Authorization": f"Bearer {_SUPABASE_ANON}",
            "Content-Type": "application/json",
        },
        json=args,
        timeout=5.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase RPC {fn} failed {resp.status_code}: {resp.text[:200]}")


class WebhookRouter:
    """Stripe billing webhook receiver."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["billing:webhook"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post("/webhook")(self.receive_webhook)

    async def receive_webhook(self, request: Request) -> dict[str, Any]:
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook secret not configured.",
            )

        body = await request.body()
        sig_header = request.headers.get("stripe-signature", "")

        try:
            event = stripe.Webhook.construct_event(body, sig_header, secret)
        except stripe.error.SignatureVerificationError as exc:
            _logger.warning("stripe_signature_mismatch reason=%s", str(exc)[:80])
            raise HTTPException(status_code=400, detail=f"Invalid signature: {exc}") from exc
        except Exception as exc:
            _logger.warning("stripe_signature_parse_failed reason=%s", type(exc).__name__)
            raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

        # `event` is a stripe.Event. Since stripe-python v15 StripeObject no
        # longer inherits from dict — .get() is gone. We use attribute access
        # for the envelope, then convert the inner `data.object` to a plain
        # dict so _apply_mutation can keep treating it like JSON.
        event_id = getattr(event, "id", "") or ""
        event_type = getattr(event, "type", "") or ""
        inner = getattr(getattr(event, "data", None), "object", None)
        data_object: dict[str, Any] = (
            inner.to_dict() if inner is not None and hasattr(inner, "to_dict") else (inner or {})
        )
        if not event_id:
            raise HTTPException(status_code=400, detail="Missing event id.")
        if not event_type:
            raise HTTPException(status_code=400, detail="Missing event type.")

        # Unknown event types: 200 no-op.
        if event_type not in _HANDLED_TYPES:
            return {"status": "processed", "event_id": event_id}

        with DBSession(engine) as db:
            if db.get(BillingEvent, event_id) is not None:
                return {"status": "processed", "event_id": event_id}

            user_id = self._apply_mutation(event_type, data_object)

            db.add(
                BillingEvent(
                    event_id=event_id,
                    processed_at=_naive_utc_now(),
                    org_id=user_id,  # column name is legacy; value is user_id now
                    event_type=event_type,
                )
            )
            db.commit()

        return {"status": "processed", "event_id": event_id}

    def _apply_mutation(self, event_type: str, obj: dict[str, Any]) -> Optional[str]:
        """Resolve the user via `client_reference_id` / metadata and upsert
        their subscription. Returns the user_id string for the ledger."""
        user_id = _extract_user_id(obj)
        if not user_id:
            _logger.warning(
                "billing.webhook missing user_id",
                extra={"event_type": event_type, "keys": list(obj.keys())},
            )
            return None

        if event_type == "customer.subscription.deleted":
            try:
                _call_supabase_rpc("cancel_user_subscription_from_polar", {"p_user_id": user_id})
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            _logger.info("billing.subscription_cancelled user=%s", user_id)
            return user_id

        plan = _extract_plan_name(obj)
        if plan not in _VALID_PLANS:
            _logger.warning(
                "billing.webhook unknown plan",
                extra={"event_type": event_type, "plan": plan},
            )
            return user_id  # ledger but skip DB mutation

        status_value = _map_status(obj.get("status"), fallback="active")
        # Extract the Stripe customer id. On checkout.session.completed it's
        # `customer`; on subscription events it's also `customer`. Persist it
        # so /billing/portal-session can open the hosted Customer Portal.
        customer_id = obj.get("customer")
        if isinstance(customer_id, str) and customer_id:
            pass
        else:
            customer_id = None
        try:
            _call_supabase_rpc(
                "set_user_subscription_from_polar",
                {
                    "p_user_id": user_id,
                    "p_plan_name": plan.capitalize(),
                    "p_status": status_value,
                    "p_stripe_customer_id": customer_id,
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        _logger.info(
            "billing.subscription_synced user=%s plan=%s status=%s customer=%s",
            user_id, plan, status_value, customer_id,
        )
        return user_id


def _extract_user_id(obj: dict[str, Any]) -> Optional[str]:
    """Stripe events carry the user id in `client_reference_id` (for Checkout
    Session) or in `metadata.user_id` (for Subscription objects, propagated
    via `subscription_data.metadata` at checkout time)."""
    raw = obj.get("client_reference_id")
    if isinstance(raw, str) and raw:
        try:
            return str(UUID(raw))
        except ValueError:
            pass
    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        raw = meta.get("user_id")
        if isinstance(raw, str) and raw:
            try:
                return str(UUID(raw))
            except ValueError:
                pass
    return None


def _extract_plan_name(obj: dict[str, Any]) -> Optional[str]:
    """Prefer the live price.nickname on the current subscription item — that
    tracks plan changes made via the Customer Portal. Fall back to
    metadata.plan (set at checkout and never updated) for events that don't
    carry an items[] array, e.g. checkout.session.completed."""
    items = (obj.get("items") or {}).get("data") or []
    if isinstance(items, list) and items:
        price = items[0].get("price") or {}
        nickname = price.get("nickname")
        if isinstance(nickname, str) and nickname:
            return nickname.lower()
        product_name = (price.get("product") or {}).get("name") if isinstance(price.get("product"), dict) else None
        if isinstance(product_name, str) and product_name:
            return product_name.lower()

    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        raw = meta.get("plan")
        if isinstance(raw, str) and raw:
            return raw.lower()
    return None


def _map_status(raw: Any, fallback: str = "active") -> str:
    """Map Stripe subscription.status to our `public.subscriptions.status` enum."""
    if not isinstance(raw, str):
        return fallback
    lowered = raw.lower()
    if lowered in {"active", "trialing"}:
        return "active"
    if lowered in {"canceled", "cancelled"}:
        return "cancelled"
    if lowered in {"incomplete", "past_due", "unpaid", "incomplete_expired"}:
        return "pending"
    return fallback


def _parse_dt(raw: Any) -> Optional[datetime]:
    """Parse ISO-8601 or unix seconds into naive UTC."""
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
