"""Single-source monthly session caps per plan (Wave-54 V4-1a).

US-V4-1 AC #1 freezes the mapping: `free=100`, `team=2000`, `org=unlimited`.
Any surface that needs to make a per-plan quota decision — the ingest paywall
in `events_router.py`, the `/api/v1/me/quota` endpoint (US-17), the frontend
upgrade banner threshold — MUST import from this module rather than hard-code.
"""
from __future__ import annotations

from typing import Final

# None = unlimited. Explicit key for every known plan so reviewers can spot a
# missing tier (e.g. a future `enterprise`) rather than silently falling through.
SESSION_CAP_BY_PLAN: Final[dict[str, int | None]] = {
    "free": 100,
    "team": 2000,
    "org": None,
}


def session_cap_for(plan: str) -> int | None:
    """Monthly session cap for `plan`; unknown plans get the free-tier cap.

    Falling back to `free` (not `None`) is intentional: if a typo or future
    rename leaks an unknown plan string to the ingest path, we'd rather block
    at the free cap than silently grant unlimited ingest.
    """
    return SESSION_CAP_BY_PLAN.get(plan, SESSION_CAP_BY_PLAN["free"])
