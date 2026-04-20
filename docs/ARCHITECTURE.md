# Architecture

*Receipt — audit-grade session receipts for AI coding agents.*

This document is the high-level system sketch: what the pieces are, how data
flows, and why we picked the stack we did. For setup see [DEVELOPMENT.md](./DEVELOPMENT.md);
for endpoint details see [API.md](./API.md); for contribution rules see
[CONTRIBUTING.md](./CONTRIBUTING.md).

---

## 1. Overview

Receipt streams every tool call and file change an AI coding agent performs
into a local-first audit store. A Claude Code hook (`receipt.sh`, installed by
`receipt init`) serializes each event from stdin and POSTs it to a FastAPI
backend at `/api/v1/sessions/events` with a bearer token. The backend persists
events in SQLite, aggregates them into per-session summaries, runs a static
red-flag scanner (secrets, destructive shell, migrations, env mutations), and
exposes a read API that a React dashboard uses to render timelines, summaries,
and compliance-audit trails.

The wedge is simple: `pip install receipt-cli && receipt init` — one command,
under 60 seconds to the first visible Receipt.

---

## 2. Topology

```
+-------------------+    stdin     +-------------------+   HTTPS POST    +-------------------+
| Claude Code       |  per-tool    | receipt.sh hook   |  Bearer rcpt_   | FastAPI backend   |
| (PostToolUse      | -----------> | (~/.claude/hooks) | --------------> | /api/v1/sessions  |
|  hook fires)      |   events     |                   |                 |  /events          |
+-------------------+              +-------------------+                 +---------+---------+
                                                                                   |
                                                                     writes events |
                                                                     + aggregates  |
                                                                                   v
                                                                         +-------------------+
                                                                         | SQLite            |
                                                                         | sessions / events |
                                                                         | / hook_tokens     |
                                                                         +---------+---------+
                                                                                   |
                                                                             reads |
                                                                                   v
                                                                         +-------------------+
                                                                         | React dashboard   |
                                                                         | (Vite SPA)        |
                                                                         |  sessions list    |
                                                                         |  session detail   |
                                                                         |  trail export     |
                                                                         +-------------------+
```

**Data flow labels:**
- **events** — append-only stream of `tool_use`, `file_change`, `token`, `error`
  rows, one POST per batch, keyed by `session_id` + bearer token.
- **sessions** — denormalized per-session rows (tools count, files count,
  tokens, cost, flags) produced server-side as events arrive.
- **trail** — single-document JSON export of a session and its full event
  history, used by compliance readers (`GET /api/v1/sessions/:id/trail`).

---

## 3. Backend stack

| Concern        | Pick                                 | Why                                                             |
|----------------|--------------------------------------|-----------------------------------------------------------------|
| Language       | Python 3.11                          | Mature async + type hints; broad hosting.                       |
| Framework      | FastAPI 0.115+                       | Pydantic v2 native, async-first, OpenAPI for free.              |
| ORM / schemas  | SQLModel                             | One class is both the table and the Pydantic schema.            |
| DB (v0)        | SQLite (single file, `data/receipt.db`) | Zero-config; one file to back up; fine for the first users.  |
| Validation     | Pydantic v2                          | Fast, typed error envelopes, bundled with FastAPI.              |
| Tests          | pytest + pytest-asyncio + httpx      | Standard FastAPI toolbox.                                       |
| Lint / format  | ruff                                 | Single tool; replaces flake8 + black + isort.                   |
| Logging        | structlog (JSON)                     | Correlation IDs via `X-Request-ID`.                             |

**v1 database path.** When a deployment outgrows SQLite (heavy concurrent
writes, multi-node dashboard, or row-level-security requirements), the backend
migrates to Postgres without a rewrite: SQLModel speaks both, and the rest of
the scaffold (middleware, auth, observability) was lifted from a Postgres-first
template. See [POSTPONED.md](../POSTPONED.md) for the v1 migration checklist.

See [DEVELOPMENT.md](./DEVELOPMENT.md) for install/run commands and
[CONTRIBUTING.md](./CONTRIBUTING.md) for the PR workflow.

---

## 4. Frontend stack

| Package         | Version  | Notes                                                          |
|-----------------|----------|----------------------------------------------------------------|
| react           | 18.3.1   | React 19 deferred; ecosystem lag.                              |
| react-dom       | 18.3.1   | Matches react.                                                 |
| vite            | 5.4.10   | Stable; skipping 6/7 churn for now.                            |
| typescript      | 5.6.3    | `strict: true`, `moduleResolution: "bundler"`.                 |
| tailwindcss     | 3.4.17   | v3, not v4 — shadcn-style ports still assume the v3 config.    |
| postcss         | 8.4.49   | Required by Tailwind v3.                                       |
| autoprefixer    | 10.4.20  | Standard pairing.                                              |

All versions are pinned exactly (no `^` prefix) so production builds match
development. State is split three ways: server data in React Query, URL-bound
filters via `useSearchParams`, ephemeral UI state in `useState`. No Redux /
Zustand in v0.

---

## 5. Data model

Three tables, all defined in SQLModel. Full field lists in [API.md](./API.md).

- **`sessions`** — one row per agent session. Denormalized aggregates (tool
  count, files touched, tokens, cost, flag list, summary text) so the list
  view renders from a single indexed read.
- **`events`** — append-only stream. One row per `tool_use`, `file_change`,
  `token` accounting, or `error`, foreign-keyed to a session, with any
  red-flag rule ids captured at write time.
- **`hook_tokens`** — bearer credentials minted by `receipt init`. Only the
  SHA-256 hash is persisted; the raw `rcpt_…` token is returned once at mint
  time. Soft-revocable via `DELETE /auth/hook-token/{id}`.

---

## 6. Key design decisions

- **SQLite for v0, not Postgres.** Zero operational surface — no service, no
  container, no network hop — and the read workload is a per-user dashboard
  browsing a few thousand sessions. Capacity envelope: roughly < 100k sessions
  per day per instance before write contention matters. When a customer
  crosses that line we swap the connection string to Postgres; the SQLModel
  layer is portable.

- **`404`, not `403`, on cross-user reads.** When a session or token row
  exists but belongs to a different user, the API returns `404 Not Found`
  rather than `403 Forbidden`. A `403` leaks the fact that an id is valid
  (and therefore worth brute-forcing); a `404` is indistinguishable from a
  never-minted id. The null-check and the owner-check collapse into one
  conditional so reviewers can grep for the pattern. One documented
  exception: deleting a hook-token of another user returns `401` because the
  hook-token is the credential itself.

- **The hook is the product.** The distribution wedge is
  `pip install receipt-cli && receipt init`: one command, < 60 seconds, first
  Receipt visible before anyone creates an account. The dashboard is the
  monetization layer on top of the hook's audit data, not the entry point.
  Anything that threatens the 60-second install promise is a regression.

---

## 7. What ships in v0, what's v1

**Shipped in v0:**
- Session ingestion hook (`receipt.sh`, installed by `receipt init`).
- Per-session timeline view (tools, files, tokens, cost, elapsed time).
- Deterministic 3-line session summary.
- Static red-flag detection (secrets, destructive shell, migrations, env
  changes, CI config).
- Search + filter on sessions list (user, date range, flagged, min cost).
- Hook-token auth (mint, list, revoke); `/health`, `/health/ready`,
  `/version`, `/metrics` ops endpoints.

**Deferred to v1 / later** (see [POSTPONED.md](../POSTPONED.md) for the full
backlog):
- **LLM-written summaries** — v0 uses a deterministic template; v1 swaps in
  an LLM-generated narrative once we've calibrated on real session shapes.
- **Weekly digest email** — scoped but not yet built.
- **Billing + team accounts + org-scoped ingest** — requires a paid tier and
  multi-tenant row-level security; lives under the v1 user-stories backlog.
- **Postgres migration + horizontal scaling** — triggered by customer load,
  not a calendar date.

---

## Further reading

- [API.md](./API.md) — endpoint reference, request/response schemas, data
  model fields.
- [DEVELOPMENT.md](./DEVELOPMENT.md) — local setup, running the backend and
  dashboard, test commands.
- [CONTRIBUTING.md](./CONTRIBUTING.md) — PR workflow, review standards, code
  style.
- [HOOK-WIRING.md](./HOOK-WIRING.md) — how `receipt init` installs the Claude
  Code hook and how to write a hook for a different agent.
