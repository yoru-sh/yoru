"""Receipt v0 — `GET /api/v1/health/deep` oncall-grade introspection probe.

Distinct from `/health` (liveness) and `/health/ready` (LB readiness, 503-on-fail).
This endpoint is structured introspection: ALWAYS returns HTTP 200, body envelope
reports per-check ok/detail. Status `"degraded"` means one or more checks failed
but the process is alive — humans read this to triage.

Three checks, run concurrently via asyncio.gather, never short-circuit:
  1. db        — `SELECT 1` via SQLModel session, hard-timeout 500ms
  2. disk      — write+fsync+stat+unlink a 1-byte tempfile under data dir
  3. env_polar — boolean presence of POLAR_API_KEY (NEVER leaks the value)
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text
from sqlmodel import Session as SQLSession

from .db import engine

DB_TIMEOUT_SEC = 0.5


def _data_dir() -> Path:
    """Directory that holds receipt.db (parent of the sqlite file)."""
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        return Path(url.database).parent
    # health_deep_router.py -> parents[5] == backend/
    return Path(__file__).resolve().parents[5] / "data"


def _check_db_sync() -> dict:
    try:
        with SQLSession(engine) as session:
            session.exec(text("SELECT 1"))
        return {"ok": True, "detail": "SELECT 1 ok"}
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__}


async def _check_db() -> dict:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_check_db_sync), timeout=DB_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        return {"ok": False, "detail": "timeout"}


def _check_disk_sync() -> dict:
    try:
        d = _data_dir()
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, delete=False) as tmp:
            tmp.write(b"x")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        st = tmp_path.stat()
        if st.st_size <= 0:
            tmp_path.unlink()
            return {"ok": False, "detail": "zero_size"}
        tmp_path.unlink()
        return {"ok": True, "detail": "writable"}
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__}


async def _check_disk() -> dict:
    return await asyncio.to_thread(_check_disk_sync)


async def _check_env_polar() -> dict:
    present = bool(os.getenv("POLAR_API_KEY"))
    return {"ok": present, "detail": "present" if present else "missing"}


class HealthDeepRouter:
    """GET /health/deep — structured introspection envelope (always HTTP 200)."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["ops"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.get("/health/deep")(self.health_deep)

    async def health_deep(self) -> dict:
        db_res, disk_res, env_res = await asyncio.gather(
            _check_db(), _check_disk(), _check_env_polar()
        )
        all_ok = db_res["ok"] and disk_res["ok"] and env_res["ok"]
        return {
            "status": "ok" if all_ok else "degraded",
            "checks": {
                "db": db_res,
                "disk": disk_res,
                "env_polar": env_res,
            },
        }
