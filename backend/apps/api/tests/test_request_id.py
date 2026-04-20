"""Gate test for wave-13 C1: request_id contextvar + middleware public surface.

Covers the C2/C3 contract:
  - `from apps.api.core.request_id import request_id_ctx` works.
  - Inbound `X-Request-ID` is echoed verbatim on the response.
  - Without the header, the server mints an id and echoes it (uuid4 hex
    is 32 chars; contract only requires length >= 12 per the spec).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.mkdtemp(prefix="receipt-reqid-")) / "test.db"
os.environ["RECEIPT_DB_URL"] = f"sqlite:///{_TMP_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.core.request_id import request_id_ctx  # noqa: E402
from apps.api.main import app  # noqa: E402


def test_request_id_ctx_is_importable_from_core_request_id():
    """Wave-13 C2/C3 gate: the contextvar must live at this path."""
    assert request_id_ctx.get() is None
    token = request_id_ctx.set("smoke-rid")
    try:
        assert request_id_ctx.get() == "smoke-rid"
    finally:
        request_id_ctx.reset(token)


def test_inbound_header_is_echoed_and_missing_header_is_minted():
    with TestClient(app) as client:
        custom = "wave13-c1-smoke-abc"
        r1 = client.get("/health", headers={"X-Request-ID": custom})
        assert r1.status_code == 200
        assert r1.headers["X-Request-ID"] == custom

        r2 = client.get("/health")
        assert r2.status_code == 200
        generated = r2.headers["X-Request-ID"]
        assert generated and generated != custom
        assert len(generated) >= 12
