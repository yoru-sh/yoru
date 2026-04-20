"""Red-flag rule scanner for Receipt v0 events.

Rule ids are STABLE identifiers (never user-facing strings). Contract:
vault/BACKEND-API-V0.md §5. Patterns are compiled once at module load.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import EventIn


# --- secret rules: scanned against content AND json.dumps(raw) ---
_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "secret_aws": re.compile(r"AKIA[0-9A-Z]{16}|aws_secret_access_key"),
    "secret_stripe": re.compile(r"sk_(?:live|test)_[0-9a-zA-Z]{24,}"),
    "secret_jwt": re.compile(
        r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    ),
    "secret_ssh_privkey": re.compile(
        r"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"
    ),
}

# --- shell_rm: tool_use + tool in {Bash, Shell} + content regex ---
_SHELL_TOOLS: frozenset[str] = frozenset({"Bash", "Shell"})
_SHELL_RM_RE = re.compile(r"(?:^|[;&\|\s])rm\s+(?:-[rfRF]+\s+)?")

# --- path rules: triggered only when kind == "file_change" ---
_MIGRATION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|/)migrations/"),
    re.compile(r"(?:^|/)alembic/versions/"),
    re.compile(r".*\.sql$"),
)
_ENV_MUTATION_RE = re.compile(r"(?:^|/)\.env(?:\..*)?$")
_CI_CONFIG_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.github/workflows/.*\.ya?ml$"),
    re.compile(r"^\.gitlab-ci\.ya?ml$"),
    re.compile(r"^\.circleci/config\.ya?ml$"),
    re.compile(r"^Dockerfile$"),
    re.compile(r"^docker-compose\.ya?ml$"),
)


def scan_event(e: "EventIn") -> list[str]:
    """Return a deduped list of rule ids triggered by ``e``.

    Order is stable: secret_* first (in declaration order), then shell_rm,
    then migration_file, env_mutation, ci_config.
    """
    flags: list[str] = []
    seen: set[str] = set()

    def _add(rule_id: str) -> None:
        if rule_id not in seen:
            seen.add(rule_id)
            flags.append(rule_id)

    content = e.content or ""
    raw_blob = json.dumps(e.raw or {})

    for rule_id, pattern in _SECRET_PATTERNS.items():
        if pattern.search(content) or pattern.search(raw_blob):
            _add(rule_id)

    if (
        e.kind == "tool_use"
        and e.tool in _SHELL_TOOLS
        and content
        and _SHELL_RM_RE.search(content)
    ):
        _add("shell_rm")

    if e.kind == "file_change" and e.path:
        path = e.path
        if any(p.search(path) for p in _MIGRATION_RES):
            _add("migration_file")
        if _ENV_MUTATION_RE.search(path):
            _add("env_mutation")
        if any(p.search(path) for p in _CI_CONFIG_RES):
            _add("ci_config")

    return flags
