# Hook Wiring

How Receipt attaches to a Claude Code session, mints a token, and starts streaming events. Read this when the README Quickstart isn't enough, or before you commit to `receipt init`.

**Status:** `v0 / MVP` · **Backend:** `http://localhost:8002` by default

---

## 1. Why a hook, not a wrapper?

Claude Code exposes a first-class hook API: any `PostToolUse` event hands a JSON blob to a user-configured script, which runs out-of-band and cannot block the agent. Receipt registers a hook. It does **not** wrap, proxy, or fork the `claude` binary — your session keeps running untouched whether Receipt is up, down, or missing entirely. The hook is a passive observer; if it fails, Claude Code doesn't notice.

## 2. Install

```bash
# Editable install from the monorepo (v0)
pip install -e receipt-cli/

# Once published on PyPI:
# pip install receipt-cli
```

Requires Python 3.10+. The only runtime dep is `httpx`. Backend must be reachable — default `http://localhost:8002`, override with `--server`.

Verify:

```bash
receipt --version           # → receipt 0.1.0
curl http://localhost:8002/health/ready    # → {"status":"ok", ...}
```

## 3. Mint a hook-token

A hook-token is an opaque `rcpt_...` string scoped to one username. It's minted once and reused for every event.

### 3a. Automatic — `receipt init`

```bash
receipt init --user you@example.com --server http://localhost:8002
```

This does three things in one step:

1. Mints a token (`POST /api/v1/auth/hook-token`).
2. Writes `~/.config/receipt/config.json` (mode `0600`) with the token + server URL.
3. Writes `~/.claude/hooks/receipt.sh` — the bash script Claude Code will invoke.

Re-run with `--force` to overwrite an existing install. Exit codes: `0` ok, `1` already installed, `2` auth/mint failed, `3` 4xx, `4` 5xx/network.

### 3b. Manual — for air-gapped, CI, or shared hosts

Mint the token with curl, then drop it into the config file yourself:

```bash
# 1. Mint
curl -sS -X POST http://localhost:8002/api/v1/auth/hook-token \
  -H 'Content-Type: application/json' \
  -d '{"user":"you@example.com"}'
# → {"token":"rcpt_...", "user_id":"...", "user":"you@example.com"}

# 2. Save it (same shape receipt init writes)
mkdir -p ~/.config/receipt && chmod 700 ~/.config/receipt
cat > ~/.config/receipt/config.json <<EOF
{"server":"http://localhost:8002","token":"rcpt_..."}
EOF
chmod 600 ~/.config/receipt/config.json

# 3. Install the bundled hook script
receipt init --token rcpt_... --server http://localhost:8002 --force
```

Mint is **unauthenticated in v0** (Supabase JWT gating lands in v1). A 422 at this step means the body is missing `user`; check your `-d` payload.

## 4. Wire the hook into Claude Code

`receipt init` drops the script at `~/.claude/hooks/receipt.sh` but does **not** edit your Claude Code settings — you register the hook yourself. Add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "~/.claude/hooks/receipt.sh"}]}
    ]
  }
}
```

Notes:

- Use `PostToolUse`, not `PreToolUse` — `PostToolUse` carries `tool_response`, which Receipt needs to classify errors.
- The outer array is a list of matcher groups (one per tool filter); the inner `hooks` array is the list of commands that fire for that group. Match-all is the empty/absent matcher.
- If you already have other `PostToolUse` hooks, append a new object to the outer array rather than nesting.

Confirm Claude Code picked it up:

```bash
ls -la ~/.claude/hooks/receipt.sh        # must be executable (0755)
jq '.hooks.PostToolUse' ~/.claude/settings.json   # must show the receipt.sh entry
```

## 5. Verify the first event arrives

Three-step smoke against a live backend:

```bash
# a. Stash the token for the curl
TOKEN=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.config/receipt/config.json")))["token"])')

# b. Run any Claude Code tool (Write, Bash, Read) in a fresh session.
#    The hook fires on each PostToolUse and POSTs to /api/v1/sessions/events.

# c. List your sessions — the new one should show up within 5 seconds.
curl -sS -H "Authorization: Bearer $TOKEN" http://localhost:8002/api/v1/sessions | jq '.items[0]'
```

Expected shape on `items[0]`:

```json
{"id":"<session-uuid>","user":"you@example.com","agent":"claude-code",
 "tools_count":1,"files_count":0,"flagged":false,"flags":[], ...}
```

No item? See §6. Existence-but-empty (0 events, no tools counted)? Also §6 — almost always a silent 4xx.

## 6. Troubleshooting

### 401 Unauthorized on `/sessions/events` or `/sessions`

Your bearer token is missing, malformed, or revoked. Check:

```bash
cat ~/.config/receipt/config.json | jq .token      # starts with rcpt_
curl -sS -X GET http://localhost:8002/api/v1/auth/hook-tokens \
  -H "Authorization: Bearer $TOKEN" | jq .         # 200 if token valid
```

Fix: re-mint via `receipt init --force --user you@example.com`. (Old token rows are soft-revoked, not deleted — the new one is what `config.json` now holds.)

### 422 Unprocessable on ingest

`EventIn` validation failed. The response envelope carries `request_id`; grep the backend log for it:

```bash
grep <request_id> /tmp/uvicorn.log    # or wherever you piped stdout
```

Most common causes in v0:

- `session_id` missing — it is the only unconditionally required field.
- Body not wrapped as `{"events":[<event>]}` — the hook always wraps, but hand-crafted curls often skip it.
- Neither `user` in body **nor** a valid `Authorization: Bearer` header — both are optional, but at least one must be present so the server can attribute the event.

### Silent fail: hook exits 0, no event ever ingested

By design, the hook ends with `curl ... >/dev/null 2>&1 || true`. It **always** exits `0` regardless of backend status — exit code is not a signal of success.

Reproduce with the real exit status visible:

```bash
# Synthetic event matching the real Claude Code stdin shape
echo '{"session_id":"smoke-manual","tool_name":"Bash","tool_input":{"command":"ls"},"hook_event_name":"PostToolUse"}' \
  | bash -x ~/.claude/hooks/receipt.sh
```

The `bash -x` trace prints every curl + Python sub-invocation. Drop `|| true` and `>/dev/null 2>&1` from a local copy of the script if you want a persistent error stream while debugging.

### Events land but `path` / `content` are null (red flags never fire)

Real Claude Code 2026 stdin delivers `tool_input.file_path` (Write/Edit/Read) and `tool_input.command` (Bash) — not the flat `path` / `content` fields that v0's `EventIn` expects. The v0 backend classifies `kind` correctly from `tool_name` but silently drops unknown top-level keys, so `path` and `content` persist as `null`. Red-flag rules that scan `content` (`shell_rm`, `secret_aws`, `env_mutation`) can't fire. This is a known v0 limitation being closed in v1 (`X-Receipt-Schema: v1` header + server-side `tool_input` unpacking).

Workaround until v1: for tests that must exercise red-flag rules, POST events with flat `content`/`path` fields directly (see `scripts/smoke-us14.sh`).

### Session appears under the wrong user / missing when filtered

When the body omits `user`, the server attaches it from the bearer token. Two failure modes:

- Body carries a hardcoded `user` that differs from the token's owner → the body wins in v0. Remove `user` from the body, let the bearer decide.
- Wrong token in `~/.config/receipt/config.json` (e.g. a CI token instead of yours) → `receipt init --force` with your real email re-mints and rewrites config.

---

## Further reading

- Project-internal specs live under `vault/` — see `vault/EVENTIN-V1-SPEC.md` for the v1 schema migration and `vault/research/claude-code-hook-stdin-2026.md` for the canonical Claude Code stdin shape.
- `docs/API.md` — full backend endpoint reference.
- `docs/ARCHITECTURE.md` — hook → backend → dashboard data flow.
