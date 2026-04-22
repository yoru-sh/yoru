"""POST /api/v1/billing/checkout-session — Stripe checkout.

Uses the official `stripe` Python SDK with per-seat quantity support.
When `STRIPE_API_KEY` is missing the handler short-circuits to a mock
redirect so the dashboard upgrade button stays demo-able without Stripe
credentials.

`client_reference_id` we send to Stripe is the authenticated user's UUID
(from their Supabase JWT). The webhook receiver uses it to resolve which
user's subscription row to upsert in `public.subscriptions` on checkout
completion.
"""
from __future__ import annotations

import os
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.api.dependencies.auth import get_current_user_id

_VALID_PLANS = ("pro", "team", "org")
_VALID_CYCLES = ("monthly", "annual")

# Stripe Price IDs (NOT product IDs) — per-seat prices you create in the
# Stripe dashboard under Products → pricing → "Recurring, per unit".
# Annual prices are -21% of (monthly × 12) — same formula as marketing.
_PRICE_ID_ENV = {
    ("pro",  "monthly"): "STRIPE_PRO_PRICE_ID",
    ("pro",  "annual"):  "STRIPE_PRO_ANNUAL_PRICE_ID",
    ("team", "monthly"): "STRIPE_TEAM_PRICE_ID",
    ("team", "annual"):  "STRIPE_TEAM_ANNUAL_PRICE_ID",
    ("org",  "monthly"): "STRIPE_ORG_PRICE_ID",
    ("org",  "annual"):  "STRIPE_ORG_ANNUAL_PRICE_ID",
}
_ORG_SEAT_PRICE_ID_ENV = {
    "monthly": "STRIPE_ORG_SEAT_PRICE_ID",
    "annual":  "STRIPE_ORG_SEAT_ANNUAL_PRICE_ID",
}


def _stripe_configured() -> bool:
    """True when STRIPE_API_KEY is present — otherwise we short-circuit to mock."""
    return bool(os.getenv("STRIPE_API_KEY", "").strip())


def _configure_stripe() -> None:
    """Set the module-level stripe.api_key from env on each call. Cheap + safe
    even if the env var isn't set (stripe module accepts None, fails clearly
    on first API call)."""
    stripe.api_key = os.environ.get("STRIPE_API_KEY", "").strip() or None


class CheckoutRequest(BaseModel):
    plan: str
    cycle: str = "monthly"  # "monthly" | "annual"
    success_url: str
    cancel_url: str
    seats: int = 1  # per-seat quantity for all paid tiers


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class CheckoutRouter:
    """Mount under `/api/v1/billing` — registers `/checkout-session`."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["billing:checkout"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.post(
            "/checkout-session",
            response_model=CheckoutResponse,
            status_code=status.HTTP_200_OK,
        )(self.create_checkout_session)

    def create_checkout_session(
        self,
        body: CheckoutRequest,
        user_id: UUID = Depends(get_current_user_id),
    ) -> CheckoutResponse:
        if body.plan not in _VALID_PLANS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown plan '{body.plan}' — must be one of {', '.join(_VALID_PLANS)}",
            )
        cycle = body.cycle if body.cycle in _VALID_CYCLES else "monthly"

        price_id = os.environ.get(_PRICE_ID_ENV[(body.plan, cycle)], "").strip()

        # Mock mode: no STRIPE_API_KEY or missing price-id env → round-trip
        # to /settings/billing with a flag so the UI explains it.
        if not _stripe_configured() or not price_id:
            mock_url = f"{body.success_url}{'&' if '?' in body.success_url else '?'}mock=1&plan={body.plan}"
            return CheckoutResponse(
                checkout_url=mock_url,
                session_id=f"cs_mock_{body.plan}",
            )

        # All paid tiers accept variable seats, clamped to [1, 200].
        quantity = max(1, min(200, body.seats))

        # Build line items. Org has a two-part fee: $99 base (flat) + $15
        # per seat. Pro/Team are single-line per-unit.
        if body.plan == "org":
            seat_price_id = os.environ.get(_ORG_SEAT_PRICE_ID_ENV[cycle], "").strip()
            if not seat_price_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="STRIPE_ORG_SEAT_PRICE_ID not configured",
                )
            line_items = [
                {
                    "price": price_id,            # $99 base
                    "quantity": 1,
                },
                {
                    "price": seat_price_id,       # $15 × seats
                    "quantity": quantity,
                    "adjustable_quantity": {"enabled": True, "minimum": 1, "maximum": 200},
                },
            ]
        else:
            line_items = [{
                "price": price_id,
                "quantity": quantity,
                "adjustable_quantity": {"enabled": True, "minimum": 1, "maximum": 200},
            }]

        _configure_stripe()
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=line_items,
                success_url=body.success_url,
                cancel_url=body.cancel_url,
                client_reference_id=str(user_id),
                # Surface the "Add promotion code" field on the hosted page.
                # Default Stripe behavior hides it — we expose it so launch /
                # beta / partner codes work without manual URL hacking.
                allow_promotion_codes=True,
                metadata={
                    "user_id": str(user_id),
                    "plan": body.plan,
                    "cycle": cycle,
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user_id),
                        "plan": body.plan,
                        "cycle": cycle,
                    },
                },
            )
        except stripe.error.StripeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe checkout create failed: {exc.user_message or str(exc)}",
            ) from exc

        return CheckoutResponse(
            checkout_url=session.url or "",
            session_id=session.id,
        )
