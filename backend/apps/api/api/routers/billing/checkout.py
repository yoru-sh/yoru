"""POST /api/v1/billing/checkout-session — US-15 Polar checkout session.

Wave-20-B C1 (atomic). The Polar SDK is mocked by default via a module-level
`_polar_client = MagicMock()` so tests + smoke curls exercise the full handler
without a live Polar account. When `POLAR_API_KEY` is set the real SDK is
instantiated at import time.

Contract reference: vault/BACKEND-API-V1.md §4.1 (full v1 shape: 303 redirect +
owner-only + env-resolved price ids). THIS endpoint is the MVP cut: 200 JSON
response with `checkout_url` + `session_id`, `plan in {team, org}`, mock SDK.
Follow-up waves (US-16 webhook, owner gate, quota) layer the rest.
"""
from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import MagicMock

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.api.routers.receipt.deps import require_current_user

_VALID_PLANS = ("team", "org")

_PLAN_ID_ENV = {
    "team": "POLAR_TEAM_PLAN_ID",
    "org": "POLAR_ORG_PLAN_ID",
}
_PLAN_ID_DEFAULT = {
    "team": "plan_team_mock",
    "org": "plan_org_mock",
}

# Deterministic namespace so the stub `_resolve_org_id(user)` is stable across
# calls for the same user string. v1 swaps this for a real membership lookup.
_ORG_NS = uuid.UUID("0e7b0f20-6b2f-4a6a-b0a1-0cbf3d1e7f00")


def _build_polar_client() -> Any:
    """Instantiate the real Polar SDK when POLAR_API_KEY is set, else MagicMock.

    Isolated so tests can import, patch the module-level `_polar_client`, and
    exercise the handler without touching the network. When the real SDK is
    unavailable (import error) we fall back to MagicMock — this keeps boot
    resilient during local dev where `polar-sdk` may not be pinned yet.
    """
    api_key = os.getenv("POLAR_API_KEY", "").strip()
    if not api_key:
        return MagicMock()
    try:
        import polar_sdk  # type: ignore[import-not-found]
    except ImportError:
        return MagicMock()
    return polar_sdk.Client(api_key)  # type: ignore[attr-defined]


# Module-level SDK client. Tests `monkeypatch.setattr` on this symbol.
_polar_client: Any = _build_polar_client()


def _resolve_org_id(user: str) -> uuid.UUID:
    """Return the caller's active org UUID.

    TODO(wave-21): replace with a real membership lookup (Supabase JWT -> org
    via `OrgMember` table). v0 returns a deterministic UUID5 derived from the
    user string — equivalent to a 1:1 personal org for now.
    """
    return uuid.uuid5(_ORG_NS, user)


class CheckoutRequest(BaseModel):
    # NOTE: `str` (not Literal) so an unknown plan falls through to the handler
    # and raises 400. Pydantic Literal would 422 before we get there, which
    # contradicts the brief's "400 on invalid plan" requirement.
    plan: str
    success_url: str
    cancel_url: str


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
        current_user: str = Depends(require_current_user),
    ) -> CheckoutResponse:
        if body.plan not in _VALID_PLANS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown plan",
            )

        plan_id = os.environ.get(
            _PLAN_ID_ENV[body.plan],
            _PLAN_ID_DEFAULT[body.plan],
        )
        org_id = _resolve_org_id(current_user)

        response = _polar_client.checkouts.create(
            plan_id=plan_id,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            client_reference_id=str(org_id),
        )

        # `str()` keeps the response JSON-serializable when `_polar_client` is a
        # MagicMock (default): `response.url` / `response.id` are MagicMock
        # attributes unless a test swaps in `MagicMock(url=..., id=...)`.
        return CheckoutResponse(
            checkout_url=str(response.url),
            session_id=str(response.id),
        )
