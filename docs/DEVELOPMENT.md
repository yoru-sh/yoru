# Development

Local setup, tests, and the edit-run-verify loop for Receipt.

## Prerequisites

- Python **3.11 or 3.12** (pinned in `backend/pyproject.toml`)
- Node **20+** (the frontend targets Vite 5 + React 18)
- [`uv`](https://docs.astral.sh/uv/) — Python package and virtualenv
  manager
- `git`

Optional: Docker + Docker Compose (for `make dev`), `curl` and `jq`.

## Clone and install

```bash
git clone <repo-url> receipt
cd receipt
make install            # = cd backend && uv sync  +  cd frontend && npm ci
```

Run either half on its own with `cd backend && uv sync` or
`cd frontend && npm ci`.

## Run locally

**Option A — native (fastest iteration):** two terminals.

```bash
# terminal 1 — backend on :8002, auto-reload
cd backend && uv run uvicorn apps.api.main:app --reload --port 8002

# terminal 2 — frontend on :5173
cd frontend && npm run dev
```

The frontend expects the backend at `http://localhost:8002`.

**Option B — Docker Compose (closer to production):**

```bash
make dev                # docker compose up --build
make down               # stop everything
```

## Run tests

```bash
# backend — pytest suite
cd backend
uv run pytest

# frontend — type-check (no unit-test runner is wired yet)
cd frontend
npx tsc --noEmit
```

The backend suite excludes integration tests by default; pass
`-m integration` to include them (they require a live backend on
`:8002`).

End-to-end smoke — installs the CLI, wires the hook, posts sample
events, asserts the red-flag detector, all under 60 seconds:

```bash
bash scripts/smoke-us14.sh
```

## Repo layout

```
.
├── backend/        FastAPI + SQLModel service (the API)
├── frontend/       Vite + React + TypeScript SPA (the dashboard)
├── receipt-cli/    pip-installable CLI that wires the Claude Code hook
├── scripts/        Operator scripts (smoke, restart, deploy, audit)
├── docs/           Public-facing docs (this file, ARCHITECTURE, API)
└── vault/          Internal design notes (not user-facing)
```

## Making a backend change

1. Edit the router or model under `backend/apps/api/api/routers/`.
2. Add or extend a test under `backend/apps/api/tests/`; run
   `cd backend && uv run pytest` until green.
3. Restart the running backend so the live process picks up the code:
   ```bash
   make restart-backend
   ```
4. Curl-verify the new behaviour against `http://localhost:8002`.

> A non-`--reload` backend keeps serving its booted build until it
> restarts. Step 3 is mandatory whenever you change router, middleware,
> or startup code outside the `--reload` dev loop.

## Making a frontend change

1. Edit the component or page under `frontend/src/`.
2. Type-check: `cd frontend && npx tsc --noEmit`
3. Production-build sanity: `cd frontend && npm run build`
4. Verify in the running dev server (`npm run dev`) and click through
   the affected flow in the browser.

## Debugging

- **Backend logs** print to stdout as structured JSON, one object per
  line. Every request carries a `request_id`; filter by it to follow a
  single call end-to-end.
- **Frontend** — browser devtools (console + network panel). The SPA
  forwards the backend's `X-Request-ID` header on every fetch, so the
  id in a failing request matches the one in the backend log.
- **CLI and hook** — `receipt init` writes its config and hook template
  under `~/.claude/`. Re-run with `--verbose` to see the shell-out.

## Further reading

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system topology and decisions
- [`API.md`](./API.md) — full HTTP reference
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — PR and commit conventions
