# Receipt API

Reader-facing reference for the Receipt HTTP API. See [HOOK-WIRING.md](./HOOK-WIRING.md) for the install → mint → hook flow.

## Base URL & auth

- **Dev:** `http://localhost:8002`
- **Deployed:** your Receipt deployment's public URL.
- **Auth:** Bearer hook-token in the `Authorization` header (`Authorization: Bearer rcpt_...`). Mint one via `POST /api/v1/auth/hook-token`.

All `/api/v1/...` routes return JSON. Ops routes (`/health`, `/version`, `/metrics`) are unauthenticated.

## Error envelope

Every error response is JSON and carries a `request_id` (echoed in the `X-Request-ID` header):

| Cause | Status | Body |
|---|---|---|
| Unhandled exception | 500 | `{"error": "Internal server error", "request_id": "<rid>"}` |
| Validation (`RequestValidationError`) | 422 | `{"error": "Validation error", "detail": [...], "request_id": "<rid>"}` |
| `HTTPException(status, detail)` | `status` | `{"detail": <detail>, "request_id": "<rid>"}` |

Tracebacks never leak into response bodies; they're logged server-side and correlated by `request_id`.

---

## Sessions

### POST /api/v1/sessions/events
Ingest a batch of Claude Code session events (1–1000 per call).

**Auth:** Bearer hook-token.

**Request:**
```bash
curl -X POST http://localhost:8002/api/v1/sessions/events \
  -H "Authorization: Bearer rcpt_..." \
  -H "Content-Type: application/json" \
  -d '{"events": [{"session_id": "sess_abc", "kind": "tool_use", "tool": "Write", "path": "README.md"}]}'
```

**Response (202):**
```json
{"accepted": 1, "session_ids": ["sess_abc"], "flagged_sessions": []}
```

**Errors:** 401 (missing/invalid bearer), 413 (>1000 events), 422 (invalid event shape).

The canonical wire contract for each event is tracked in `EVENTIN-V1-SPEC` (see further reading). Red-flag scanning runs per event; any event flags roll up into `session.flags` and flip `session.flagged=true`.

### GET /api/v1/sessions
List sessions owned by the caller, most recent first.

**Auth:** Bearer hook-token.

**Query params:**

| Name | Type | Default | Notes |
|---|---|---|---|
| `from_ts` | ISO datetime | — | `started_at >= from_ts` |
| `to_ts` | ISO datetime | — | `started_at <= to_ts` |
| `flagged` | bool | — | filter by red-flag status |
| `min_cost` | float | — | `cost_usd >= min_cost` |
| `limit` | int | 50 | 1–200 |
| `offset` | int | 0 | pagination |

**Request:**
```bash
curl "http://localhost:8002/api/v1/sessions?flagged=true&limit=10" \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):**
```json
{
  "items": [
    {"id": "sess_abc", "user": "you@example.com", "agent": "claude-code",
     "started_at": "2026-04-20T08:00:00", "ended_at": null,
     "tools_count": 12, "files_count": 3, "tokens_input": 0, "tokens_output": 0,
     "cost_usd": 0.0, "flagged": true, "flags": ["shell_rm"]}
  ],
  "total": 1, "limit": 10, "offset": 0
}
```

**Errors:** 401, 422 (bad query types).

### GET /api/v1/sessions/{id}
Full detail for one session: aggregates + up to the last 1000 events (ordered ascending by `ts`).

**Auth:** Bearer hook-token.

**Request:**
```bash
curl http://localhost:8002/api/v1/sessions/sess_abc \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):**
```json
{
  "id": "sess_abc", "user": "you@example.com", "agent": "claude-code",
  "started_at": "2026-04-20T08:00:00", "ended_at": "2026-04-20T08:15:00",
  "tools_count": 12, "files_count": 3, "tokens_input": 0, "tokens_output": 0,
  "cost_usd": 0.0, "flagged": false, "flags": [],
  "files_changed": ["README.md", "src/main.py"],
  "tools_called": ["Write", "Edit", "Bash"],
  "summary": null,
  "events": [{"id": 1, "ts": "2026-04-20T08:00:01", "kind": "tool_use",
              "tool": "Write", "path": "README.md", "content": null,
              "tokens_input": 0, "tokens_output": 0, "cost_usd": 0.0, "flags": []}]
}
```

**Errors:** 401, 404 (unknown id *or* cross-user — 404 is deliberate, it avoids leaking existence).

### GET /api/v1/sessions/{id}/trail
Single-file compliance-audit export of a session + every event (no 1000-event cap). Sent with `Content-Disposition: attachment` so `curl -OJ` and browsers save straight to disk.

**Auth:** Bearer hook-token.

**Request:**
```bash
curl -OJ http://localhost:8002/api/v1/sessions/sess_abc/trail \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):**
```json
{
  "session": { "...": "all fields from GET /sessions/{id} minus events" },
  "events":  [ "...every event, ts ascending..." ],
  "exported_at": "2026-04-20T09:00:00Z",
  "schema_version": "v0"
}
```

**Errors:** 401, 404 (unknown *or* cross-user).

### POST /api/v1/sessions/{id}/summary
Generate (or regenerate) a deterministic 3-line summary and persist it on the session. Idempotent — re-POST overwrites.

**Auth:** Bearer hook-token.

**Request:**
```bash
curl -X POST http://localhost:8002/api/v1/sessions/sess_abc/summary \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):**
```json
{
  "session_id": "sess_abc",
  "summary": "12 tools across 3 files in 900s.\nTokens: 0→0  Cost: $0.00.\nFlags: none.",
  "generated_at": "2026-04-20T09:00:00"
}
```

**Errors:** 401, 404 (unknown *or* cross-user).

### GET /api/v1/sessions/{id}/summary
Retrieve a previously generated summary.

**Auth:** Bearer hook-token.

**Request:**
```bash
curl http://localhost:8002/api/v1/sessions/sess_abc/summary \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):** same shape as POST.

**Errors:** 401, 404 (unknown id, cross-user, or summary not yet generated).

---

## Auth — hook tokens

### POST /api/v1/auth/hook-token
Mint a new hook-token. The raw value is returned **once**; only its sha256 hash is persisted.

**Auth:** none in v0.

**Request:**
```bash
curl -X POST http://localhost:8002/api/v1/auth/hook-token \
  -H "Content-Type: application/json" \
  -d '{"user": "you@example.com", "label": "laptop"}'
```

**Response (201):**
```json
{"token": "rcpt_xxxxxxxxxxxxxxxxxxxxxxxx", "user_id": "<uuid>", "user": "you@example.com"}
```

**Errors:** 422 (missing `user`, or `user`/`label` longer than 128).

### GET /api/v1/auth/hook-tokens
List every hook-token owned by the caller (active + revoked), sorted newest-first. Raw values are never returned.

**Auth:** Bearer hook-token.

**Request:**
```bash
curl http://localhost:8002/api/v1/auth/hook-tokens \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):**
```json
[{"id": "<uuid>", "label": "laptop", "created_at": "2026-04-20T08:00:00",
  "last_used_at": "2026-04-20T08:30:00", "revoked_at": null}]
```

**Errors:** 401.

### DELETE /api/v1/auth/hook-token/{id}
Soft-revoke a hook-token (stamps `revoked_at`). Idempotent — re-DELETE returns 204 without re-stamping.

**Auth:** Bearer hook-token.

**Request:**
```bash
curl -X DELETE http://localhost:8002/api/v1/auth/hook-token/<uuid> \
  -H "Authorization: Bearer rcpt_..."
```

**Response:** 204 (no body).

**Errors:** 401 (missing bearer *or* token belongs to another user — spec calls for 401 here, not 404, because the hook-token IS the credential), 404 (unknown `id`).

---

## Dashboard

### GET /api/v1/dashboard/team
Per-user session aggregates over a window (default: last 7 days).

**Auth:** Bearer hook-token.

**Query params:**

| Name | Type | Default | Notes |
|---|---|---|---|
| `since` | ISO datetime | `now - 7d` | lower bound on `started_at` |

**Request:**
```bash
curl "http://localhost:8002/api/v1/dashboard/team?since=2026-04-13T00:00:00" \
  -H "Authorization: Bearer rcpt_..."
```

**Response (200):** per-user aggregate rows (sessions count, total cost, flagged count).

**Errors:** 401, 422 (bad `since`).

---

## Ops

### GET /health
Liveness probe. Returns `{"status": "ok"}` while the ASGI app is alive; never touches the DB so blips don't trigger restart loops. `GET /healthz` is an alias.

```bash
curl http://localhost:8002/health
```

### GET /health/ready
Readiness probe. Runs three sub-probes (DB round-trip, data-dir writable, token store queryable), each hard-timeboxed. `GET /readyz` is an alias.

```bash
curl http://localhost:8002/health/ready
```

**Response (200):** all probes ok. **Response (503):** at least one failed; body carries per-probe status.

### GET /version
Build identity. Reads version from `pyproject.toml`, adds Python runtime, and (best-effort) git SHA.

```bash
curl http://localhost:8002/version
# {"version": "0.1.0", "python": "3.11.9", "git_sha": "abc1234"}
```

### GET /metrics
Prometheus text exposition (`text/plain; version=0.0.4`).

```bash
curl http://localhost:8002/metrics
```

---

## Further reading
- Live interactive docs at `http://localhost:8002/docs` (FastAPI-generated Swagger).
- Canonical event wire contract: `vault/EVENTIN-V1-SPEC.md`.
- Error envelope rationale and middleware wiring: `vault/ERROR-HANDLING-V0.md`.
- Frozen v0 schemas and endpoint contracts: `vault/BACKEND-API-V0.md`.
