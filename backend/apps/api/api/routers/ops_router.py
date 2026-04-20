"""Ops endpoints — liveness, readiness, version.

Split rationale:
- `/health` is a pure liveness probe (no DB). K8s/Docker restarts on failure.
- `/health/ready` does a DB ping; failing it removes the pod from load-balancing
  without killing it, so transient DB blips don't trigger restart loops.
- `/version` reports the shipped version (from pyproject.toml) + git sha
  (best-effort) + python runtime — handy for "which build is this" debugging.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.api.routers.receipt.db import engine


def _read_version_from_pyproject() -> str:
    """Read [project].version from backend/pyproject.toml. Fallback 'unknown'."""
    # ops_router.py -> parents[4] == backend/
    pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
    try:
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        return str(data.get("project", {}).get("version") or "unknown")
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown"


def _best_effort_git_sha() -> str | None:
    """Return short git SHA, or None if git unavailable / not a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


_VERSION = _read_version_from_pyproject()
_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


class OpsRouter:
    """Liveness, readiness, version."""

    def __init__(self) -> None:
        self.router = APIRouter(tags=["ops"])
        self._setup_routes()

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self) -> None:
        self.router.get("/health")(self.health)
        self.router.get("/health/ready")(self.ready)
        self.router.get("/version")(self.version)

    async def health(self) -> dict:
        return {"status": "ok"}

    async def ready(self) -> JSONResponse:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            reason = type(exc).__name__
            return JSONResponse(
                status_code=503,
                content={"status": "unready", "reason": reason},
            )
        return JSONResponse(status_code=200, content={"status": "ok"})

    async def version(self) -> dict:
        payload: dict = {"version": _VERSION, "python": _PYTHON}
        sha = _best_effort_git_sha()
        if sha:
            payload["git_sha"] = sha
        return payload
