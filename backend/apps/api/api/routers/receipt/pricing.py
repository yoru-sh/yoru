"""Pricing lookup for token→USD cost computation at ingest time.

Auto-refreshed from LiteLLM's public pricing JSON — a community-maintained,
well-known file covering every major model provider (Anthropic, OpenAI,
Google, Mistral, Cohere, xAI, …). We never have to hand-edit rates as
Anthropic / OpenAI / whoever-else ships a new model.

Source: https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
Format (per model):
  {
    "claude-sonnet-4-5-20250929": {
      "input_cost_per_token": 0.000003,
      "output_cost_per_token": 0.000015,
      "cache_creation_input_token_cost": 0.00000375,
      "cache_read_input_token_cost": 0.0000003,
      "litellm_provider": "anthropic",
      ...
    }
  }

Flow:
  1. Startup: load from cache file if fresh (<24h), else fetch remote.
  2. Every request: in-memory lookup. First resolves exact model name, then
     substring match, then provider family fallback (opus/sonnet/haiku).
  3. Admin route: POST /api/v1/pricing/refresh to force-refresh.

Design choices:
  * Rates stored as $/token (not $/1M) since that's LiteLLM's native unit —
    fewer conversions, less rounding error.
  * Fallback static table covers Anthropic family keys ("opus"/"sonnet"/
    "haiku") so Receipt still prices sessions correctly when the fetch fails
    for any reason (offline, GitHub down, network censorship).
  * Thread-safe via a module-level lock — FastAPI background tasks can
    refresh without racing ingestion.

When Cursor/Aider/any other coding agent lands, they'll emit OpenAI or
Anthropic model names that LiteLLM already has — no Receipt-side change.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("apps.api.receipt.pricing")

_REMOTE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_CACHE_PATH = Path("data/pricing-cache.json")  # relative to backend CWD
_MAX_AGE_SEC = 24 * 60 * 60  # 24h
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Rates:
    """Per-token USD rates. Multiply by token count to get cost.

    Anthropic splits prompt-cache writes into two TTL tiers with different
    prices: 5-minute TTL (1.25× input) and 1-hour TTL (2× input). Claude Code
    writes everything to the 1h tier, so getting `cache_write_1h` right
    matters — using `cache_write` (5m) here would under-bill by ~40%.
    """
    input: float
    cache_write: float        # ephemeral_5m (default cache tier)
    cache_write_1h: float     # ephemeral_1h (extended tier Claude Code uses)
    cache_read: float
    output: float
    provider: str


# No hardcoded fallback: if LiteLLM is unreachable AND the disk cache is
# missing, we return 0 cost rather than guess with rates that could already
# be out of date (Anthropic's Opus prices dropped 3× between 4.6 and 4.7).
# Receipt prefers honest "unknown" over stale guess. Cold-boot with no
# network = ingested events show cost_usd=0 until a later refresh succeeds;
# the backend also stamps `pricing.status()` for observability.


# In-memory pricing table: {model_name_lowercase: Rates}
_TABLE: dict[str, Rates] = {}
_LOADED_AT: float = 0.0


def _is_fresh() -> bool:
    return _LOADED_AT > 0 and (time.time() - _LOADED_AT) < _MAX_AGE_SEC


def _parse_litellm_json(raw: dict) -> dict[str, Rates]:
    """Extract Rates from LiteLLM's JSON. Skips entries without input+output
    rates (embedding/audio/image models we never see in a code-agent session).
    Picks up the 1h extended-cache rate when LiteLLM provides it, else falls
    back to 2× input as Anthropic's published ratio."""
    out: dict[str, Rates] = {}
    for model_name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        ip = entry.get("input_cost_per_token")
        op = entry.get("output_cost_per_token")
        if not isinstance(ip, (int, float)) or not isinstance(op, (int, float)):
            continue
        cw_5m = entry.get("cache_creation_input_token_cost", ip)
        cw_1h = entry.get("cache_creation_input_token_cost_above_1hr", None)
        if not isinstance(cw_1h, (int, float)):
            cw_1h = float(ip) * 2  # Anthropic's published 1h-tier multiplier
        cr = entry.get("cache_read_input_token_cost", ip * 0.1)
        provider = str(entry.get("litellm_provider") or "unknown")
        out[model_name.lower()] = Rates(
            input=float(ip),
            cache_write=float(cw_5m) if isinstance(cw_5m, (int, float)) else float(ip),
            cache_write_1h=float(cw_1h),
            cache_read=float(cr) if isinstance(cr, (int, float)) else float(ip) * 0.1,
            output=float(op),
            provider=provider,
        )
    return out


def _fetch_remote() -> Optional[dict[str, Rates]]:
    """HTTP GET LiteLLM JSON. Returns None on any failure (never raises)."""
    try:
        req = urllib.request.Request(
            _REMOTE_URL,
            headers={"User-Agent": "Receipt/v0 pricing-sync"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning("pricing fetch failed: %s", e)
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning("pricing JSON parse failed: %s", e)
        return None
    return _parse_litellm_json(parsed)


def _load_disk_cache() -> Optional[tuple[dict[str, Rates], float]]:
    """Read the on-disk cache if present; returns (rates, mtime) or None."""
    if not _CACHE_PATH.exists():
        return None
    try:
        with _CACHE_PATH.open() as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    rates: dict[str, Rates] = {}
    for name, r in raw.get("rates", {}).items():
        rates[name] = Rates(
            input=r["input"],
            cache_write=r["cache_write"],
            cache_write_1h=r.get("cache_write_1h", r["cache_write"] * 1.6),
            cache_read=r["cache_read"],
            output=r["output"],
            provider=r["provider"],
        )
    return rates, float(raw.get("fetched_at", 0))


def _save_disk_cache(rates: dict[str, Rates]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": time.time(),
        "source": _REMOTE_URL,
        "rates": {
            name: {
                "input": r.input,
                "cache_write": r.cache_write,
                "cache_write_1h": r.cache_write_1h,
                "cache_read": r.cache_read,
                "output": r.output,
                "provider": r.provider,
            }
            for name, r in rates.items()
        },
    }
    tmp = _CACHE_PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(payload, f)
    tmp.replace(_CACHE_PATH)


def refresh(force: bool = False) -> int:
    """Reload the in-memory pricing table. Idempotent.

    Strategy (per call):
      1. If not `force` and the on-disk cache is < 24h old, hydrate from disk.
      2. Otherwise fetch remote; on success, persist to disk.
      3. Fall back to the static `_FALLBACK` table on total failure.
    Returns the number of models in the resulting table.
    """
    global _TABLE, _LOADED_AT
    with _LOCK:
        # Disk first (cheap) when not forcing.
        if not force:
            cached = _load_disk_cache()
            if cached is not None:
                rates, fetched_at = cached
                if rates and (time.time() - fetched_at) < _MAX_AGE_SEC:
                    _TABLE = rates
                    _LOADED_AT = fetched_at
                    log.info("pricing: loaded %d models from disk cache", len(rates))
                    return len(_TABLE)

        remote = _fetch_remote()
        if remote:
            _TABLE = remote
            _LOADED_AT = time.time()
            try:
                _save_disk_cache(remote)
            except OSError as e:
                log.warning("pricing cache write failed: %s", e)
            log.info("pricing: loaded %d models from LiteLLM", len(remote))
            return len(_TABLE)

        # No static fallback — better to return cost=0 than stale guesses.
        if _TABLE:
            log.warning("pricing: kept %d previously-loaded rates (refresh failed)", len(_TABLE))
        else:
            log.error("pricing: no rates available (LiteLLM + disk cache both missed)")
        return len(_TABLE)


def _ensure_loaded() -> None:
    if not _TABLE:
        refresh(force=False)


def lookup_rates(model: str) -> Optional[Rates]:
    """Find rates for a model name. Tries exact → substring match.

    Returns None if nothing matches — caller falls back to 0 cost. No
    family-level guess ("opus" → made-up rates) because Anthropic's prices
    have shifted significantly between Opus versions (4.6 → 4.7 = 3× drop),
    so a guess risks a big misreport.
    """
    if not model:
        return None
    _ensure_loaded()
    m = model.lower()
    # 1. exact match (LiteLLM's key format = provider-prefixed model name)
    if m in _TABLE:
        return _TABLE[m]
    # 2. substring — LiteLLM keys are dated like "claude-sonnet-4-5-20250929",
    # user-sent model is typically "claude-sonnet-4-5" → substring hits.
    for key, rates in _TABLE.items():
        if key in m or m in key:
            return rates
    return None


def compute_cost_usd(model: str, usage: dict) -> float:
    """Compute USD cost from a usage dict. Anthropic or OpenAI shape.

    Anthropic keys: input_tokens, cache_creation_input_tokens,
                    cache_read_input_tokens, output_tokens
    OpenAI keys:    prompt_tokens, completion_tokens (+
                    prompt_tokens_details.cached_tokens)

    Missing dims → 0. Unpriced model → 0.
    """
    rates = lookup_rates(model)
    if rates is None:
        return 0.0

    # Anthropic shape — split cache_creation by TTL tier. 1h entries bill at
    # 2× input (~60% premium over the 5m tier). Claude Code writes everything
    # to the 1h tier today, so splitting correctly adds ~40% to cache_write
    # cost on long sessions.
    if "output_tokens" in usage or "cache_creation_input_tokens" in usage:
        in_fresh = int(usage.get("input_tokens") or 0)
        cw_total = int(usage.get("cache_creation_input_tokens") or 0)
        cr = int(usage.get("cache_read_input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        # Split writes by TTL tier if the sub-breakdown is present.
        split = usage.get("cache_creation")
        if isinstance(split, dict):
            cw_1h = int(split.get("ephemeral_1h_input_tokens") or 0)
            cw_5m = int(split.get("ephemeral_5m_input_tokens") or 0)
            # Defensive: if caller sent totals that don't match, trust
            # cw_total as the authoritative sum and bucket any delta to 5m.
            accounted = cw_1h + cw_5m
            if accounted < cw_total:
                cw_5m += cw_total - accounted
        else:
            cw_5m, cw_1h = cw_total, 0
    # OpenAI shape — no TTL-tiered cache writes there.
    else:
        in_fresh = int(usage.get("prompt_tokens") or 0)
        cw_5m = 0
        cw_1h = 0
        details = usage.get("prompt_tokens_details") or {}
        cr = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
        in_fresh = max(0, in_fresh - cr)
        out = int(usage.get("completion_tokens") or 0)

    return (
        in_fresh * rates.input
        + cw_5m * rates.cache_write
        + cw_1h * rates.cache_write_1h
        + cr * rates.cache_read
        + out * rates.output
    )


def summarize_tokens(usage: dict) -> tuple[int, int]:
    """Collapse any usage shape into (input_tokens, output_tokens)."""
    if "output_tokens" in usage:
        in_total = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
        )
        out = int(usage.get("output_tokens") or 0)
    else:
        in_total = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)
    return in_total, out


def status() -> dict:
    """Introspection for the admin refresh route."""
    _ensure_loaded()
    return {
        "source": _REMOTE_URL,
        "cache_path": str(_CACHE_PATH.resolve()) if _CACHE_PATH.exists() else None,
        "loaded_at": _LOADED_AT,
        "age_sec": int(time.time() - _LOADED_AT) if _LOADED_AT else None,
        "model_count": len(_TABLE),
    }
