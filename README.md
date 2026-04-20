# Receipt

**Status:** `v0 / MVP` &middot; **Python:** `3.10+` &middot; **License:** internal (v0)

Audit-grade session receipts for autonomous AI coding agents. Receipt captures every
Claude Code session as a structured ledger — every tool call, file edit, red-flag event,
token cost, and elapsed time — and turns it into a reviewable timeline. Install once,
see your first Receipt within 60 seconds.

```text
$ receipt init --user you@example.com --server http://localhost:8002
→ hook installed: ~/.claude/hooks/receipt.sh
→ config saved : ~/.config/receipt/config.json  (token rcpt_••••)
→ next Claude Code session will stream events to /api/v1/sessions/events
```

---

## 1. Install

Two pieces: the CLI (wires the Claude Code hook) and the backend (stores events,
computes red flags, serves the timeline). Both run locally for v0.

```bash
git clone <repo-url> overnight-saas
cd overnight-saas

# CLI — editable install from the monorepo
pip install -e receipt-cli/

# Backend — uv-managed FastAPI app on :8002
make install           # uv sync + npm ci
make restart-backend   # uvicorn on :8002, idempotent
curl http://localhost:8002/health/ready    # -> {"status":"ok", ...}
```

CLI runtime dep: `httpx`. Backend runtime: Python 3.11 + SQLite (no Postgres, Redis, or
external services in v0).

## 2. 60-second smoke

End-to-end from a fresh checkout — mirrors `scripts/smoke-us14.sh`:

```bash
# 1. install the CLI (skip if already done above)
pip install -e receipt-cli/

# 2. wire the hook for your email
receipt init --user you@example.com --server http://localhost:8002

# 3. post 3 events in one session (one flagged — touches .env)
curl -sf -X POST http://localhost:8002/api/v1/sessions/events \
  -H 'Content-Type: application/json' \
  -d '{"events":[
    {"session_id":"demo","user":"you@example.com","kind":"tool_use","tool":"Bash","content":"ls -la"},
    {"session_id":"demo","user":"you@example.com","kind":"file_change","path":".env","content":"API_KEY=redacted"},
    {"session_id":"demo","user":"you@example.com","kind":"tool_use","tool":"Edit","path":"src/app.py"}
  ]}'
```

The response carries `flagged_sessions: ["demo"]` — the `.env` edit tripped the
`env_mutation` red-flag rule. Under 60 seconds, hook to Receipt, no dashboard required.

## 3. Hook into Claude Code

`receipt init` drops a bash hook at `~/.claude/hooks/receipt.sh` that forwards each tool
call to the backend with a bearer token. Wire it into Claude Code by adding a
`PostToolUse` entry to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "~/.claude/hooks/receipt.sh"}]}
    ]
  }
}
```

The hook uses `curl --max-time 2 || true` — it never blocks the agent, even if the
backend is down. See [`docs/HOOK-WIRING.md`](docs/HOOK-WIRING.md) for event shape, auth,
and troubleshooting.

## 4. What you get

- **Timeline** — per-session view of every tool call, file change, and edit, ordered
  and addressable by URL. `GET /api/v1/sessions/{id}`.
- **Red flags** — eight static rules detect secrets (AWS / Stripe / JWT / SSH keys),
  destructive shell (`rm -rf`), migration files, `.env` mutations, and CI config writes.
  Flagged sessions surface on the list page and badge per event.
- **3-line TL;DR** — deterministic v0 summary per session (tools used, files touched,
  total cost). `POST /api/v1/sessions/{id}/summary` generates; `GET` returns the cache.

## 5. Docs — deep dives

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — stack, layout, boundaries
- [`docs/API.md`](docs/API.md) — full endpoint reference + auth model
- [`docs/HOOK-WIRING.md`](docs/HOOK-WIRING.md) — Claude Code hook shape + event schema
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — dev loop, tests, restart-backend

## 6. License

Internal / unlicensed while v0 is in flight. A proper OSS or commercial license will
land alongside the first public tag. v0 is an MVP — API shapes, auth, and on-disk
formats may change without notice before v1.
