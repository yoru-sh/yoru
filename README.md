# Yoru

Audit trail for autonomous AI coding agents. This is the source-of-truth monorepo
for [yoru.sh](https://yoru.sh) — Cloud backend, dashboard, marketing site, CLI, and
self-host docs. Dual-licensed: **MIT** for the CLI, **AGPL-3.0** for the server.

> **Public mirrors** (synced from this monorepo on every `main` push):
> - CLI (MIT) — [github.com/yoru-sh/cli](https://github.com/yoru-sh/cli) · `pip install yoru-cli`
> - Server + dashboard (AGPL) — [github.com/yoru-sh/yoru](https://github.com/yoru-sh/yoru) · `docker-compose up`
>
> The marketing site (`marketing/`) stays Cloud-only and is not mirrored.

## Layout

| Directory          | License | What it is                                                 |
|--------------------|---------|------------------------------------------------------------|
| `yoru-cli/`        | MIT     | `pip install yoru-cli` — Claude Code hook installer        |
| `backend/`         | AGPL    | FastAPI service, SQLite ingest, Supabase multi-tenant      |
| `frontend/`        | AGPL    | React dashboard (app.yoru.sh)                              |
| `packages/receipt-ui/` | AGPL | Shared component library consumed by `frontend/` and `marketing/` |
| `marketing/`       | AGPL    | yoru.sh landing + pricing (Cloud-only, not mirrored)       |
| `docs/`            | AGPL    | Self-host guide, architecture, hook spec                   |

## Local dev (solo-dev workflow)

```bash
# backend on :8002
make install             # uv sync + npm ci
make restart-backend     # idempotent
curl http://localhost:8002/health/ready

# CLI (editable from the monorepo)
pip install -e yoru-cli/
yoru init --server http://localhost:8002
```

See [`docs/SELF-HOST.md`](docs/SELF-HOST.md) for running Yoru on your own infra,
and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the stack layout.

## License

- CLI (`yoru-cli/`): [MIT](./yoru-cli/LICENSE) — free to bundle anywhere, no copyleft.
- Everything else: [AGPL-3.0](./LICENSE) — modifying the server and exposing it to other users triggers the source-distribution clause. Fine for internal company self-hosting; call us before running a competing Cloud on top of this code.

See [`LICENSING.md`](./LICENSING.md) for the rationale.
