"""Admin / introspection endpoints for the pricing table.

GET  /pricing       → current state (source, model count, age) + minimal sample
POST /pricing/refresh → force refresh from LiteLLM, return status

Auth: mirrors the other receipt admin routes — bearer required. v0 treats any
authenticated user as able to read; refresh is also authenticated but not
admin-gated yet (small surface, low risk — revisit once roles land).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import require_current_user
from . import pricing


class PricingRouter:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/pricing", tags=["receipt:pricing"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.get("")(self.status)
        self.router.post("/refresh")(self.refresh)

    def status(
        self,
        _current_user: str = Depends(require_current_user),
    ) -> dict:
        st = pricing.status()
        # Include a small sample (first 5 Anthropic entries) for sanity.
        sample: dict[str, dict] = {}
        for name, rates in list(pricing._TABLE.items())[:20]:  # type: ignore[attr-defined]
            if rates.provider == "anthropic":
                sample[name] = {
                    "input_per_mtok": round(rates.input * 1e6, 3),
                    "cache_write_per_mtok": round(rates.cache_write * 1e6, 3),
                    "cache_read_per_mtok": round(rates.cache_read * 1e6, 3),
                    "output_per_mtok": round(rates.output * 1e6, 3),
                }
        return {**st, "sample_anthropic": sample}

    def refresh(
        self,
        _current_user: str = Depends(require_current_user),
    ) -> dict:
        count = pricing.refresh(force=True)
        return {"refreshed": True, "model_count": count, **pricing.status()}
