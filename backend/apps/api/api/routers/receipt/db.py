"""SQLite engine + FastAPI session dependency for Receipt v0.

File path: backend/data/receipt.db — resolved from this module's location so
behavior is identical under uvicorn, pytest, and Docker.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

# apps/api/api/routers/receipt/db.py -> parents[5] == backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_DB_PATH = _BACKEND_ROOT / "data" / "receipt.db"

# Allow override via env (used by tests and docker).
_DB_URL = os.environ.get("RECEIPT_DB_URL") or f"sqlite:///{_DEFAULT_DB_PATH}"

if _DB_URL.startswith("sqlite:///") and _DB_URL != "sqlite:///:memory:":
    Path(_DB_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_db() -> None:
    """Create tables if absent. Safe to call repeatedly (idempotent)."""
    from . import models  # noqa: F401 — registers SQLModel tables
    from apps.api.api.routers.billing import models as billing_models  # noqa: F401
    from apps.api.api.models import webhooks as webhook_models  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency — yields a SQLModel Session."""
    with Session(engine) as session:
        yield session
