# Receipt — Operations Runbook

Day-2 ops reference for Receipt v0. Read alongside `vault/SLO-V0.md`
(targets), `deploy/prometheus/alerts.yml` (rules), and `scripts/deploy.sh`
(rollback).

SHIPMENT-READINESS.md is the ship-decision doc. This one is after-ship:
"Receipt is running and something is wrong, what do I do?"

## What to watch

| Signal | Where | Healthy baseline |
|---|---|---|
| HTTP 5xx rate | Prom `http_requests_total{status=~"5.."}` | <0.5% |
| POST /events p95 | Prom `http_request_duration_seconds{path=".../events"}` | <200ms |
| GET /sessions p95 | Prom `http_request_duration_seconds{path=".../sessions"}` | <300ms |
| /health/ready success | Prom `http_requests_total{path="/health/ready",status="200"}` / total | ≥99.5% |
| Hook-token mint success | Prom path `/api/v1/auth/hook-token` status=~"2.." | ≥99.0% |
| Request-ID log volume | Backend stdout (JSON log) | any spike = triage |

Dashboards (future wave): none shipped in v0. Drop `deploy/prometheus/` into
a prom cluster and use built-in alerts + query UI at `:9090` for now.

## Red-flag signals (page someone)

1. **`ReceiptHealthReadyFailing` firing** — load-balancer may stop routing.
   Restart backend (`scripts/restart-backend.sh`), check `/health/ready`
   sub-probe failures for root cause. See [§slo-3](#slo-3-readiness-failing).

2. **`ReceiptHookTokenMintErrorRateHigh` firing** — first-install flow
   broken. Distribution wedge critical: `pip install receipt-cli && receipt
   init` cannot complete without a working hook-token endpoint. Check auth
   router logs by request-id. See [§slo-4](#slo-4-hook-token-mint).

3. **5xx spike >1%** — triage by request-id in JSON logs; most likely cause
   is SQLite lock contention (single-writer) or middleware exception. See
   [§slo-5](#slo-5-5xx-rate).

4. **Secret-pattern red-flag rate spike** — look at ingested events for
   `secret_aws` / `secret_stripe` / `secret_jwt` rule hits. Users may be
   accidentally uploading creds. Not a system outage but an abuse signal;
   contact user by request-id before their credential leaks further.

## Rollback

`scripts/deploy.sh` is idempotent and supports rollback. Smoke evidence:
`vault/audits/deploy-sh-smoke-wave-12.md`.

```bash
# Roll back to previous tag (deploy.sh records last-known-good)
bash scripts/deploy.sh rollback

# Or manual: restart previous image tag
docker compose -f docker-compose.prod.yml pull receipt-backend:<prev-tag>
docker compose -f docker-compose.prod.yml up -d
```

Always verify post-rollback:

```bash
curl -sf http://<host>/health/ready | jq
curl -sf http://<host>/version | jq
```

If `/health/ready` is 200 and `/version` returns the expected prior SHA,
rollback is complete. Then confirm the failing signal from §What to watch
has returned to baseline within 5 minutes before clearing the page.

## Runbook anchors (referenced by alerts.yml)

### slo-1-events-latency-high

**Alert:** `ReceiptEventsP95LatencyHigh`.
**Likely causes:** DB lock contention, large batch ingestion (1000 events),
red-flag regex backtracking.
**First actions:**
1. `curl -s http://<host>/metrics | grep 'http_request_duration_seconds_count{.*events'`
   to read the recent rate.
2. Tail JSON logs filtered by `path="/api/v1/sessions/events"` — look for
   one request-id repeating (regex backtracking on pathological payload).
3. If p95 >1s sustained for 10+ minutes, `bash scripts/restart-backend.sh`
   to clear the connection pool and kill any stuck SQLite writer.

### slo-2-sessions-latency-high

**Alert:** `ReceiptSessionsP95LatencyHigh`.
**Likely causes:** large `limit=200` queries, missing index on filter
column, N+1 on session→events expansion.
**First actions:**
1. Read `vault/PERF-V0-QUERY-AUDIT.md` for the list of known slow queries
   and their index requirements.
2. Verify `sessions.started_at` index present:
   `sqlite3 <db-path> ".indexes sessions"` should list `ix_sessions_started_at`.
3. If missing, the wave-15 N+1 guard pytest likely regressed — rerun
   `pytest backend/apps/api/tests/integration/test_perf_queries.py -v`
   to confirm, and roll back per [§Rollback](#rollback) if red.

### slo-3-readiness-failing

**Alert:** `ReceiptHealthReadyFailing`.
**Likely causes:** DB file permission error, disk full, hook_tokens table
missing (schema drift).
**First actions:**
1. `curl -s http://<host>/health/ready | jq '.probes'` — read the
   `detail` field on the failing sub-probe.
2. Each sub-probe points at a concrete recovery step:
   - `db_roundtrip` fails → check disk space (`df -h`) and DB file
     permissions (`ls -l <db-path>`).
   - `uploads_writable` fails → verify the uploads directory is writable
     by the backend process user; `chown` or remount.
   - `hook_token_signing_key` fails → signing key env var missing or
     unreadable; confirm `HOOK_TOKEN_SIGNING_KEY` is set in the process
     environment, then restart.
3. After the underlying fix, `bash scripts/restart-backend.sh` and re-curl
   `/health/ready` to confirm all probes green.

### slo-4-hook-token-mint

**Alert:** `ReceiptHookTokenMintErrorRateHigh`.
**Likely causes:** auth router DB error, input validation drift
post-deploy, signing key rotation left stale tokens.
**First actions:**
1. From an ops machine:
   ```bash
   curl -X POST http://<host>/api/v1/auth/hook-token \
     -H 'Content-Type: application/json' \
     -d '{"user":"smoke@test"}'
   ```
2. If 2xx, mint itself works — the problem is input/schema drift from a
   real client. Pull request-id from the 4xx/5xx log spike and diff the
   request body against the current `EventIn` schema in
   `backend/apps/api/api/routers/auth/schemas.py`.
3. If 5xx, check for DB errors in the auth router logs
   (`grep '"logger":"auth"' <stdout> | grep '"level":"error"'`).
4. If signing key was rotated in the last hour, any mint that validates
   against the old key will 401 — confirm `HOOK_TOKEN_SIGNING_KEY` matches
   the value from the pre-rotation deploy and roll the change back if not.

### slo-5-5xx-rate

**Alert:** `Receipt5xxBurst`.
**Likely causes:** unhandled exception in new code path, upstream
dependency timeout, SQLite lock timeout under bursty ingestion.
**First actions:**
1. Grep JSON logs for `"level":"error"` in the last 10 minutes and sort
   by stacktrace fingerprint — a single route responsible for >80% of the
   burst is the usual pattern.
2. If the spike started within 5 minutes of a deploy, roll back per
   [§Rollback](#rollback) first, ask questions second.
3. If no recent deploy, check `/metrics` for SQLite-specific error
   counters and consider a restart to clear wedged writers.

## Incident contacts

TODO: morning-human fills in. For v0 single-operator:

- Ops-on-call: `<placeholder — set before first prod deploy>`
- Escalation: `<placeholder>`
- Status page: not shipped in v0

## Reference

- SLOs + error budgets: `vault/SLO-V0.md`
- Alert rules: `deploy/prometheus/alerts.yml`
- Scrape config: `deploy/prometheus/prometheus.yml`
- Observability primitives: `vault/OBSERVABILITY-V0.md`
- Deploy / rollback: `scripts/deploy.sh`, `vault/SHIPMENT-READINESS.md`
- Restart helper: `scripts/restart-backend.sh`
- Smoke tests: `scripts/smoke-us14.sh`, `scripts/smoke-real-hook.sh`
