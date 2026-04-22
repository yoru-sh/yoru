"""POST /api/v1/billing/portal-session — Stripe Customer Portal.

Creates a hosted billing portal session for the authenticated user. The
portal handles all subscription management (upgrade / downgrade / cancel /
update payment method / download invoices) — we don't need separate
endpoints for each. The user is redirected there, makes changes, and
Stripe fires webhook events that flow back through billing/webhook.py to
update our DB.

Pre-req: the user must have a `stripe_customer_id` in public.subscriptions
(set by the webhook on their first checkout.session.completed).

When STRIPE_API_KEY is missing or the user has never checked out, we
return 404 with a helpful message rather than silently failing.
"""
from __future__ import annotations

import os
from typing import Any, Optional
from uuid import UUID

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.api.dependencies.auth import (
    get_current_user_id,
    get_current_user_token,
)


class PortalSessionRequest(BaseModel):
    return_url: str
    # Optional deep-link: when set, the portal opens directly on the
    # subscription-update confirmation screen for this target plan.
    # Bypasses the config-level `subscription_update.products` (which the
    # Stripe test-mode API silently drops — see portal docs).
    target_plan: Optional[str] = None  # "pro" | "team" | "cancel"
    target_cycle: Optional[str] = "monthly"  # "monthly" | "annual"


class PortalSessionResponse(BaseModel):
    portal_url: str


_PLAN_PRICE_ENV = {
    ("pro", "monthly"):  "STRIPE_PRO_PRICE_ID",
    ("pro", "annual"):   "STRIPE_PRO_ANNUAL_PRICE_ID",
    ("team", "monthly"): "STRIPE_TEAM_PRICE_ID",
    ("team", "annual"):  "STRIPE_TEAM_ANNUAL_PRICE_ID",
}


def _stripe_configured() -> bool:
    return bool(os.getenv("STRIPE_API_KEY", "").strip())


def _configure_stripe() -> None:
    stripe.api_key = os.environ.get("STRIPE_API_KEY", "").strip() or None


def _lookup_customer_id(user_token: str, user_id: UUID) -> str | None:
    """Fetch the stripe_customer_id stored on the user's active subscription
    via Supabase PostgREST using the caller's JWT so RLS applies."""
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        return None
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    try:
        resp = httpx.get(
            f"{supabase_url}/rest/v1/subscriptions",
            headers={
                "apikey": anon,
                "Authorization": f"Bearer {user_token}",
                "Accept": "application/json",
            },
            params={
                "select": "stripe_customer_id",
                "user_id": f"eq.{user_id}",
                "status": "eq.active",
                "limit": 1,
            },
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400:
        return None
    rows = resp.json() or []
    if not rows:
        return None
    cid = rows[0].get("stripe_customer_id")
    return cid if isinstance(cid, str) and cid else None


class PortalRouter:
    """Mount under `/api/v1/billing` — registers `/portal-session`."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["billing:portal"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post(
            "/portal-session",
            response_model=PortalSessionResponse,
            status_code=status.HTTP_200_OK,
        )(self.create_portal_session)

    def create_portal_session(
        self,
        body: PortalSessionRequest,
        user_id: UUID = Depends(get_current_user_id),
        user_token: str = Depends(get_current_user_token),
    ) -> PortalSessionResponse:
        if not _stripe_configured():
            # Mock mode: send them to the return_url with a flag so the UI
            # can show a demo-mode toast.
            sep = "&" if "?" in body.return_url else "?"
            return PortalSessionResponse(
                portal_url=f"{body.return_url}{sep}mock=portal",
            )

        customer_id = _lookup_customer_id(user_token, user_id)
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No Stripe customer found for this user. Complete a "
                    "checkout first so a customer record is created."
                ),
            )

        _configure_stripe()

        flow_data = self._build_flow_data(customer_id, body)

        try:
            kwargs: dict[str, Any] = {
                "customer": customer_id,
                "return_url": body.return_url,
            }
            if flow_data is not None:
                kwargs["flow_data"] = flow_data
            # Optional override — points at a specific portal configuration
            # (e.g. one with `subscription_update.enabled=true` and non-empty
            # products). When unset, Stripe uses the account's default config.
            config_id = os.environ.get("STRIPE_PORTAL_CONFIG_ID", "").strip()
            if config_id:
                kwargs["configuration"] = config_id
            session = stripe.billing_portal.Session.create(**kwargs)
        except stripe.error.StripeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe portal create failed: {exc.user_message or str(exc)}",
            ) from exc

        return PortalSessionResponse(portal_url=session.url or "")

    def _build_flow_data(
        self, customer_id: str, body: PortalSessionRequest
    ) -> dict[str, Any] | None:
        """Per-session deep-link into the portal's update/cancel flow.

        Bypasses `configuration.features.subscription_update.products` which
        the Stripe test-mode API silently drops. When `target_plan` is None
        the portal opens on its default overview.
        """
        target = (body.target_plan or "").strip().lower()
        if not target:
            return None

        sub = self._active_subscription(customer_id)
        if sub is None:
            # Nothing to update — land them on the generic portal rather than
            # failing: they'll still see their (cancelled/expired) history.
            return None

        if target == "cancel":
            return {
                "type": "subscription_cancel",
                "subscription_cancel": {"subscription": sub.id},
            }

        if target in ("pro", "team"):
            cycle = (body.target_cycle or "monthly").strip().lower()
            env_name = _PLAN_PRICE_ENV.get((target, cycle))
            if not env_name:
                return None
            price_id = os.environ.get(env_name, "").strip()
            if not price_id:
                return None

            items = getattr(sub, "items", None)
            data = getattr(items, "data", None) if items is not None else None
            if not data:
                return None

            # Multi-item subs only happen on custom Org contracts (base plan
            # + per-seat add-ons). Those are sales-managed — reject here so
            # a stale UI can't accidentally flatten an Org contract to a
            # self-serve tier.
            if len(data) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Your subscription is custom-priced and must be "
                        "changed via sales (hello@opentruth.ch)."
                    ),
                )
            item_id = data[0].id

            return {
                "type": "subscription_update_confirm",
                "subscription_update_confirm": {
                    "subscription": sub.id,
                    "items": [{"id": item_id, "price": price_id}],
                },
            }

        return None

    def _active_subscription(self, customer_id: str) -> Any | None:
        try:
            subs = stripe.Subscription.list(
                customer=customer_id, status="active", limit=1
            )
        except stripe.error.StripeError:
            return None
        data = getattr(subs, "data", []) or []
        return data[0] if data else None
