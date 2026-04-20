"""Unit tests for red_flags.scan_event — one positive + one negative per rule.

Runs standalone: `uv run pytest apps/api/tests/test_receipt/test_red_flags.py -q`.
"""
from __future__ import annotations

from typing import Any

from apps.api.api.routers.receipt.models import EventIn
from apps.api.api.routers.receipt.red_flags import scan_event


def _ev(**overrides: Any) -> EventIn:
    base: dict[str, Any] = {
        "session_id": "s1",
        "user": "u1",
        "kind": "tool_use",
    }
    base.update(overrides)
    return EventIn(**base)


# ---------- secret_aws ----------

def test_secret_aws_positive_content():
    e = _ev(kind="tool_use", tool="Bash", content="export K=AKIAIOSFODNN7EXAMPLE")
    assert "secret_aws" in scan_event(e)


def test_secret_aws_positive_raw_keyword():
    e = _ev(kind="error", raw={"env": {"aws_secret_access_key": "xxx"}})
    assert "secret_aws" in scan_event(e)


def test_secret_aws_negative():
    e = _ev(kind="tool_use", tool="Bash", content="ls -la /tmp")
    assert "secret_aws" not in scan_event(e)


# ---------- secret_stripe ----------

def test_secret_stripe_positive():
    e = _ev(kind="error", content="key=sk_test_abcdefghijklmnopqrstuvwx0")
    assert "secret_stripe" in scan_event(e)


def test_secret_stripe_negative():
    e = _ev(kind="error", content="sk_foo or sk_live_short")
    assert "secret_stripe" not in scan_event(e)


# ---------- secret_jwt ----------

def test_secret_jwt_positive():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig_part-123"
    e = _ev(kind="error", content=f"Authorization: Bearer {token}")
    assert "secret_jwt" in scan_event(e)


def test_secret_jwt_negative():
    e = _ev(kind="error", content="eyJhbGci alone no dots or body")
    assert "secret_jwt" not in scan_event(e)


# ---------- secret_ssh_privkey ----------

def test_secret_ssh_privkey_positive():
    e = _ev(
        kind="file_change",
        path="id_rsa",
        content="-----BEGIN OPENSSH PRIVATE KEY-----\nabcdef\n-----END",
    )
    assert "secret_ssh_privkey" in scan_event(e)


def test_secret_ssh_privkey_negative():
    e = _ev(kind="error", content="BEGIN PRIVATE data...")
    assert "secret_ssh_privkey" not in scan_event(e)


# ---------- shell_rm ----------

def test_shell_rm_positive():
    e = _ev(kind="tool_use", tool="Bash", content="rm -rf /tmp/cache")
    assert "shell_rm" in scan_event(e)


def test_shell_rm_positive_chained():
    e = _ev(kind="tool_use", tool="Shell", content="cd /tmp && rm file.txt")
    assert "shell_rm" in scan_event(e)


def test_shell_rm_negative_wrong_tool():
    e = _ev(kind="tool_use", tool="Edit", content="rm -rf /tmp")
    assert "shell_rm" not in scan_event(e)


def test_shell_rm_negative_benign_content():
    e = _ev(kind="tool_use", tool="Bash", content="ls -la")
    assert "shell_rm" not in scan_event(e)


def test_shell_rm_negative_substring_rm_inside_word():
    # "warm" contains "rm" but not preceded by separator/start.
    e = _ev(kind="tool_use", tool="Bash", content="warm cookies")
    assert "shell_rm" not in scan_event(e)


# ---------- migration_file ----------

def test_migration_file_positive_migrations_dir():
    e = _ev(kind="file_change", path="app/migrations/0001_init.py")
    assert "migration_file" in scan_event(e)


def test_migration_file_positive_alembic():
    e = _ev(kind="file_change", path="backend/alembic/versions/abc123.py")
    assert "migration_file" in scan_event(e)


def test_migration_file_positive_sql():
    e = _ev(kind="file_change", path="db/schema.sql")
    assert "migration_file" in scan_event(e)


def test_migration_file_negative():
    e = _ev(kind="file_change", path="app/models.py")
    assert "migration_file" not in scan_event(e)


def test_migration_file_negative_wrong_kind():
    # path looks like a migration but the event isn't a file_change.
    e = _ev(kind="tool_use", tool="Edit", path="app/migrations/0001.py")
    assert "migration_file" not in scan_event(e)


# ---------- env_mutation ----------

def test_env_mutation_positive_root():
    e = _ev(kind="file_change", path=".env")
    assert "env_mutation" in scan_event(e)


def test_env_mutation_positive_nested():
    e = _ev(kind="file_change", path="backend/.env.local")
    assert "env_mutation" in scan_event(e)


def test_env_mutation_negative():
    e = _ev(kind="file_change", path="README.md")
    assert "env_mutation" not in scan_event(e)


# ---------- ci_config ----------

def test_ci_config_positive_github_workflows():
    e = _ev(kind="file_change", path=".github/workflows/ci.yml")
    assert "ci_config" in scan_event(e)


def test_ci_config_positive_dockerfile():
    e = _ev(kind="file_change", path="Dockerfile")
    assert "ci_config" in scan_event(e)


def test_ci_config_positive_compose():
    e = _ev(kind="file_change", path="docker-compose.yaml")
    assert "ci_config" in scan_event(e)


def test_ci_config_negative():
    e = _ev(kind="file_change", path="src/main.py")
    assert "ci_config" not in scan_event(e)


# ---------- misc / dedupe ----------

def test_dedupe_same_rule_twice():
    # AWS key in both content AND raw — should appear once.
    e = _ev(
        kind="error",
        content="AKIAIOSFODNN7EXAMPLE",
        raw={"leaked": "AKIAIOSFODNN7EXAMPLE"},
    )
    flags = scan_event(e)
    assert flags.count("secret_aws") == 1


def test_benign_event_returns_empty_list():
    e = _ev(kind="tool_use", tool="Edit", content="small change", path="README.md")
    assert scan_event(e) == []
