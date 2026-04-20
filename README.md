# overnight-saas

Receipt — audit-grade session receipts for autonomous AI coding agents.

## Dev loop

- `make install` — `uv sync` (backend) + `npm ci` (frontend)
- `make dev` — docker compose up (api + frontend dev server)
- `make test` / `make lint` / `make build`

## Backend lifecycle

After any change under `backend/apps/api/`, run `make restart-backend`.
