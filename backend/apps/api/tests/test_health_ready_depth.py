"""Depth tests for /health/ready — 3-probe breakdown per BACKEND-API-V0.md §4.11.

These tests override `ops_router.engine` with a fresh file-backed SQLite so
they stay isolated from test_receipt/conftest.py's in-memory engine (shared
across the test collection — without StaticPool, each connection sees an
empty DB, so the CREATE TABLE in probe A and SELECT in probe B race).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

from apps.api.api.routers import ops_router as ops_router_module
from apps.api.api.routers.receipt import models  # noqa: F401 — registers tables
from apps.api.main import app

PROBE_NAMES = ["db_roundtrip", "uploads_writable", "hook_token_signing_key"]


@pytest.fixture()
def ready_engine(monkeypatch):
    """File-backed SQLite with receipt tables pre-created.

    File-backed (not :memory:) so the data_dir probe has a real writable
    parent dir, and so every connect() from the probe pool sees the same
    tables.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="receipt-ready-depth-"))
    db_path = tmpdir / "test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(ops_router_module, "engine", eng)
    return eng


def test_health_ready_depth_happy_path(ready_engine):
    with TestClient(app) as client:
        r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert [p["name"] for p in body["probes"]] == PROBE_NAMES
    for probe in body["probes"]:
        assert probe["status"] == "ok", probe
        assert probe["detail"]


def test_health_ready_depth_db_failure_reports_all_probes(ready_engine, monkeypatch):
    """DB engine raises → overall unready, HTTP 503, ALL 3 probes still reported."""

    class _BrokenEngine:
        url = ready_engine.url  # keeps _resolve_data_dir happy

        def connect(self):
            raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(ops_router_module, "engine", _BrokenEngine())

    with TestClient(app) as client:
        r = client.get("/health/ready")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unready"
    assert [p["name"] for p in body["probes"]] == PROBE_NAMES

    by_name = {p["name"]: p for p in body["probes"]}
    assert by_name["db_roundtrip"]["status"] == "fail"
    assert by_name["db_roundtrip"]["detail"] == "RuntimeError"
    assert by_name["hook_token_signing_key"]["status"] == "fail"
    # Filesystem probe is independent of the DB engine — still ok.
    assert by_name["uploads_writable"]["status"] == "ok"
