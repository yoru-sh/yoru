"""Structured JSON logging — stdlib only.

Emits one JSON object per log record to stdout, keyed for request correlation:
  {ts, level, msg, request_id, path, method, status, duration_ms, user_id?}

Extra fields on a LogRecord (e.g. logger.info("...", extra={"status": 200}))
are merged into the JSON envelope, so callers can decorate records without
reaching into the formatter.

Call `configure_logging()` once at process boot (main.py does this). Use
`get_logger(name)` elsewhere — it returns a stdlib Logger with the JSON
handler already wired.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# Keys that LogRecord always carries — we drop these when harvesting `extra`.
_STANDARD_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}

_CORE_FIELDS = ("request_id", "path", "method", "status", "duration_ms", "user_id")


class JsonFormatter(logging.Formatter):
    """Serialize a LogRecord to a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        envelope: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
            "request_id": _request_id_ctx.get(),
        }
        user_id = _user_id_ctx.get()
        if user_id is not None:
            envelope["user_id"] = user_id

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS or key.startswith("_"):
                continue
            envelope[key] = value

        if record.exc_info:
            envelope["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(envelope, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger. Idempotent."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_receipt_json", False):
            return
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._receipt_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def set_request_id(request_id: str | None) -> Any:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Any) -> None:
    _request_id_ctx.reset(token)


def set_user_id(user_id: str | None) -> Any:
    return _user_id_ctx.set(user_id)


def reset_user_id(token: Any) -> None:
    _user_id_ctx.reset(token)


def current_request_id() -> str | None:
    return _request_id_ctx.get()
