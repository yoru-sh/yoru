"""init_sentry() no-op contract — no DSN, or DSN + missing SDK."""
from __future__ import annotations

import builtins

from apps.api.core.sentry import init_sentry


def test_no_dsn_returns_false(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False


def test_empty_dsn_returns_false(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "   ")
    assert init_sentry() is False


def test_dsn_set_but_sdk_missing(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@y.ingest.sentry.io/1")

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ImportError(f"mocked missing: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert init_sentry() is False
