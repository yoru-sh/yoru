"""CORS allowlist enforcement — wave-13-B2.

Verifies that `main.py` builds its CORSMiddleware from CORS_ALLOWED_ORIGINS
env and that disallowed origins get no Access-Control-Allow-Origin echo.

Each test reloads `apps.api.main` so the module-level env read picks up
the test's desired allowlist config. `configure_logging()` and handler
registration are idempotent, so reload is safe.
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

# Point Receipt DB at a tmp file BEFORE importing the app — the engine is
# constructed at module-import time (and re-built on reload), and :memory:
# would lose tables across pool connections.
_TMP_DB = Path(tempfile.mkdtemp(prefix="receipt-cors-")) / "test.db"
os.environ["RECEIPT_DB_URL"] = f"sqlite:///{_TMP_DB}"

import apps.api.main as main_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _rebuild_app(cors_env: str | None):
    """Reload main.py with the given CORS_ALLOWED_ORIGINS value (None = unset)."""
    if cors_env is None:
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
    else:
        os.environ["CORS_ALLOWED_ORIGINS"] = cors_env
    importlib.reload(main_module)
    return main_module.app


_PREFLIGHT_HEADERS_COMMON = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization, content-type",
}


def test_preflight_from_disallowed_origin_does_not_echo() -> None:
    app = _rebuild_app("https://allowed.example")
    with TestClient(app) as client:
        resp = client.options(
            "/api/v1/sessions/events",
            headers={
                "Origin": "https://evil.example",
                **_PREFLIGHT_HEADERS_COMMON,
            },
        )
    acao = resp.headers.get("Access-Control-Allow-Origin")
    # Starlette's CORSMiddleware responds 400 to disallowed preflights AND
    # omits the ACAO header. We accept either no header or a header that
    # does NOT echo the evil origin.
    assert acao != "https://evil.example", (
        f"disallowed origin was echoed — status={resp.status_code} "
        f"ACAO={acao!r} body={resp.text}"
    )


def test_preflight_from_allowed_origin_is_echoed() -> None:
    app = _rebuild_app("https://allowed.example")
    with TestClient(app) as client:
        resp = client.options(
            "/api/v1/sessions/events",
            headers={
                "Origin": "https://allowed.example",
                **_PREFLIGHT_HEADERS_COMMON,
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://allowed.example"


def test_default_allowlist_permits_vite_dev_origin() -> None:
    app = _rebuild_app(None)
    with TestClient(app) as client:
        resp = client.options(
            "/api/v1/sessions/events",
            headers={
                "Origin": "http://localhost:5173",
                **_PREFLIGHT_HEADERS_COMMON,
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
