"""Readiness probes for /health/ready (BACKEND-API-V0.md §4.11).

Three independent probes, each hard-timeboxed at 500ms:
  1. db_roundtrip           — SELECT 1 + write-read on `health_probe` table
  2. uploads_writable       — create+fsync+stat+unlink tombstone under DATA_DIR
  3. hook_token_signing_key — SELECT count(*) FROM hook_tokens (auth stack loadable)

Probes run concurrently in a ThreadPoolExecutor so total wall time stays <2s
even if one hits the timeout. Failures never short-circuit the others — the
returned list always has 3 entries in stable order.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

PROBE_TIMEOUT_SEC = 0.5


def _probe_db_roundtrip(engine: Engine) -> tuple[str, str]:
    """SELECT 1 + upsert-then-readback on a single-row health_probe table."""
    t0 = time.perf_counter()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS health_probe ("
                "key INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        stamp = str(int(time.time() * 1000))
        conn.execute(
            text(
                "INSERT INTO health_probe (key, value) VALUES (1, :v) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"v": stamp},
        )
        row = conn.execute(
            text("SELECT value FROM health_probe WHERE key = 1")
        ).first()
        if row is None or row[0] != stamp:
            raise RuntimeError("health_probe roundtrip mismatch")
        conn.commit()
    return "ok", f"{int((time.perf_counter() - t0) * 1000)}ms"


def _probe_uploads_writable(data_dir: Path) -> tuple[str, str]:
    """Write+fsync+stat+unlink a tombstone file. Detects read-only FS."""
    t0 = time.perf_counter()
    data_dir.mkdir(parents=True, exist_ok=True)
    tombstone = data_dir / ".health-probe"
    fd = os.open(tombstone, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, b"probe")
        os.fsync(fd)
    finally:
        os.close(fd)
    tombstone.stat()
    tombstone.unlink()
    return "ok", f"{int((time.perf_counter() - t0) * 1000)}ms"


def _probe_hook_token_signing_key(engine: Engine) -> tuple[str, str]:
    """v0 semantics: confirm the HookToken table is queryable (auth stack loadable).

    Probe name is future-proofed for when hook tokens become signed rather
    than hashed; today the check is that the auth-backing store responds.
    """
    t0 = time.perf_counter()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT count(*) FROM hook_tokens")).first()
    count = int(row[0]) if row else 0
    return "ok", f"count={count} {int((time.perf_counter() - t0) * 1000)}ms"


def _resolve_data_dir(engine: Engine) -> Path:
    """Derive the on-disk data dir from the engine URL (sqlite file parent)."""
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return Path(url.database).parent
    # ops_probes.py -> parents[4] == backend/
    return Path(__file__).resolve().parents[4] / "data"


def _collect(name: str, fut) -> dict:
    try:
        status, detail = fut.result(timeout=PROBE_TIMEOUT_SEC)
        return {"name": name, "status": status, "detail": detail}
    except FuturesTimeoutError:
        return {"name": name, "status": "fail", "detail": "timeout"}
    except Exception as exc:
        return {"name": name, "status": "fail", "detail": type(exc).__name__}


def run_readiness_probes(engine: Engine) -> list[dict]:
    """Execute all 3 probes concurrently. Always returns 3 entries, stable order."""
    data_dir = _resolve_data_dir(engine)
    specs: list[tuple[str, Callable[[], tuple[str, str]]]] = [
        ("db_roundtrip", lambda: _probe_db_roundtrip(engine)),
        ("uploads_writable", lambda: _probe_uploads_writable(data_dir)),
        ("hook_token_signing_key", lambda: _probe_hook_token_signing_key(engine)),
    ]
    pool = ThreadPoolExecutor(max_workers=len(specs))
    try:
        futures = [(name, pool.submit(fn)) for name, fn in specs]
        return [_collect(name, fut) for name, fut in futures]
    finally:
        # Timed-out probes may still be running; don't block shutdown on them.
        pool.shutdown(wait=False, cancel_futures=True)
