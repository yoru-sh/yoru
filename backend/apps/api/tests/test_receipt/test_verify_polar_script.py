"""Subprocess-level tests for scripts/verify-polar.sh.

Invokes the bash script with a stdlib-mocked Polar API + mocked backend
checkout endpoint. No real network calls; no new deps.

Skipped at collection time if bash or the script is absent (C1 not yet
merged, or CI runner without bash).

Run: `uv run pytest apps/api/tests/test_receipt/test_verify_polar_script.py -q`
"""
from __future__ import annotations

import http.server
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
SCRIPT = REPO_ROOT / "scripts" / "verify-polar.sh"

if shutil.which("bash") is None or not SCRIPT.exists():
    pytest.skip(
        f"verify-polar.sh unavailable at {SCRIPT} or bash missing; "
        "C1 (scripts/verify-polar.sh) not yet merged.",
        allow_module_level=True,
    )


Route = tuple[str, str]          # (method, path_prefix)
Response = tuple[int, str]       # (status, body)
RouteMap = dict[Route, Response]


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: RouteMap = {}

    def _match(self) -> Response | None:
        path = self.path.split("?", 1)[0]
        for (method, prefix), resp in self.routes.items():
            if method == self.command and (path == prefix or path.startswith(prefix)):
                return resp
        return None

    def _reply(self) -> None:
        hit = self._match()
        status, body = hit if hit else (404, '{"error":"unmapped"}')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:
        self._reply()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._reply()

    def log_message(self, *args, **kwargs) -> None:  # silence access log
        return


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mock_api() -> tuple[str, Callable[[RouteMap], None]]:
    """Yields (base_url, set_routes). One server handles both Polar + backend."""
    port = _free_port()

    class _PerTestHandler(_Handler):
        routes: RouteMap = {}

    server = http.server.HTTPServer(("127.0.0.1", port), _PerTestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_routes(routes: RouteMap) -> None:
        _PerTestHandler.routes = dict(routes)

    try:
        yield f"http://127.0.0.1:{port}", set_routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_env(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        # Placeholder values — mocked API accepts any bearer; script shouldn't
        # care what these are, only that they're non-empty.
        "POLAR_API_KEY=polar_test_placeholder_key\n"
        "POLAR_ORGANIZATION_ID=org_test_placeholder\n"
        "POLAR_PRODUCT_ID_TEAM_MONTHLY=prod_team_m_test\n"
        "POLAR_PRODUCT_ID_TEAM_ANNUAL=prod_team_a_test\n"
        "POLAR_PRODUCT_ID_ORG_MONTHLY=prod_org_m_test\n"
        "POLAR_PRODUCT_ID_ORG_ANNUAL=prod_org_a_test\n"
        "POLAR_WEBHOOK_SECRET=whsec_test_placeholder\n",
        encoding="utf-8",
    )
    return path


def _run(*, env_file: Path | None, base_url: str | None, extra: dict[str, str] | None = None):
    env = os.environ.copy()
    if base_url is not None:
        env["POLAR_API_BASE"] = base_url
        env["BACKEND_API_BASE"] = base_url
    if env_file is not None:
        env["ENV_FILE"] = str(env_file)
    if extra:
        env.update(extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------- Green path ----------

_GREEN_ORGS_BODY = (
    '{"items":[{"id":"org_test_placeholder","name":"Receipt Test Org",'
    '"slug":"receipt-test"}],"pagination":{"total_count":1,"max_page":1}}'
)
_GREEN_PRODUCT_BODY = (
    '{"id":"prod_team_m_test","name":"Team Monthly","is_recurring":true,'
    '"prices":[{"amount_type":"fixed","price_amount":2900,"price_currency":"usd"}]}'
)
_GREEN_CHECKOUT_BODY = (
    '{"checkout_url":"https://polar.sh/checkout/cs_test_123","id":"cs_test_123"}'
)


def test_all_green_exits_zero(tmp_path: Path, mock_api) -> None:
    base_url, set_routes = mock_api
    set_routes(
        {
            ("GET", "/v1/organizations"): (200, _GREEN_ORGS_BODY),
            ("GET", "/v1/products/"): (200, _GREEN_PRODUCT_BODY),
            ("POST", "/api/v1/billing/checkout-session"): (200, _GREEN_CHECKOUT_BODY),
        }
    )
    env_file = _write_env(tmp_path / "backend" / ".env")

    result = _run(env_file=env_file, base_url=base_url)

    assert result.returncode == 0, (
        f"expected 0 exit; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ALL GREEN" in result.stdout, (
        f"expected 'ALL GREEN' in stdout; got:\n{result.stdout}"
    )


# ---------- Red paths ----------

def test_invalid_api_key_exits_nonzero(tmp_path: Path, mock_api) -> None:
    base_url, set_routes = mock_api
    set_routes(
        {
            ("GET", "/v1/organizations"): (
                401,
                '{"type":"authentication_error","detail":"invalid api key"}',
            ),
        }
    )
    env_file = _write_env(tmp_path / "backend" / ".env")

    result = _run(env_file=env_file, base_url=base_url)

    assert result.returncode != 0, (
        f"expected non-zero exit; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "[✗]" in combined, (
        f"expected RED marker '[✗]' for key check; got:\n{combined}"
    )


def test_missing_product_id_exits_nonzero(tmp_path: Path, mock_api) -> None:
    base_url, set_routes = mock_api
    set_routes(
        {
            ("GET", "/v1/organizations"): (200, _GREEN_ORGS_BODY),
            ("GET", "/v1/products/"): (404, '{"type":"not_found","detail":"product not found"}'),
            ("POST", "/api/v1/billing/checkout-session"): (200, _GREEN_CHECKOUT_BODY),
        }
    )
    env_file = _write_env(tmp_path / "backend" / ".env")

    result = _run(env_file=env_file, base_url=base_url)

    assert result.returncode != 0, (
        f"expected non-zero; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "[✗]" in combined, f"expected RED marker on products line; got:\n{combined}"


def test_missing_env_file_exits_nonzero(tmp_path: Path, mock_api) -> None:
    base_url, _ = mock_api
    bogus = tmp_path / "does-not-exist" / ".env"
    assert not bogus.exists()

    result = _run(env_file=bogus, base_url=base_url)

    assert result.returncode != 0, (
        f"expected non-zero when env missing; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "env" in combined or "not found" in combined or "missing" in combined, (
        f"expected script to mention missing env; got:\n{result.stdout}\n{result.stderr}"
    )


def test_checkout_returns_non_polar_url_exits_nonzero(tmp_path: Path, mock_api) -> None:
    """Optional 5th: backend returns a checkout_url pointing at a non-Polar host.

    The script should flag this as a misconfiguration (checkout provider
    should be polar.sh, not stripe.com or similar).
    """
    base_url, set_routes = mock_api
    set_routes(
        {
            ("GET", "/v1/organizations"): (200, _GREEN_ORGS_BODY),
            ("GET", "/v1/products/"): (200, _GREEN_PRODUCT_BODY),
            ("POST", "/api/v1/billing/checkout-session"): (
                200,
                '{"checkout_url":"https://checkout.stripe.com/c/pay/cs_foo","id":"cs_foo"}',
            ),
        }
    )
    env_file = _write_env(tmp_path / "backend" / ".env")

    result = _run(env_file=env_file, base_url=base_url)

    assert result.returncode != 0, (
        f"expected non-zero when checkout url is non-polar; "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "[✗]" in combined, f"expected RED marker on checkout line; got:\n{combined}"
