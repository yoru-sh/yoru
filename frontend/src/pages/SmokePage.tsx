import { useCallback, useState } from "react"
import { EmptyState } from "../components/ui/EmptyState"

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8002/api/v1"

type RowStatus = "idle" | "running" | "ok" | "fail" | "pending"

interface Row {
  label: string
  method: string
  path: string
  status: RowStatus
  latency_ms?: number
  error?: string
  note?: string
}

const INITIAL_ROWS: Row[] = [
  { label: "ingest synthetic batch (tool_use + file_change + error)", method: "POST", path: "/sessions/events", status: "idle" },
  { label: "list sessions", method: "GET", path: "/sessions", status: "idle" },
  { label: "session detail", method: "GET", path: "/sessions/{id}", status: "idle" },
  { label: "generate summary", method: "POST", path: "/sessions/{id}/summary", status: "idle" },
  { label: "retrieve summary", method: "GET", path: "/sessions/{id}/summary", status: "idle" },
  { label: "trail export (pending if backend not shipped)", method: "GET", path: "/sessions/{id}/trail", status: "idle" },
]

interface FetchResult<T> {
  ok: boolean
  status: number
  latency_ms: number
  body?: T
  errorText?: string
}

async function timedFetch<T>(
  path: string,
  init: RequestInit,
): Promise<FetchResult<T>> {
  const t0 = performance.now()
  const res = await fetch(`${API_BASE}${path}`, init)
  const latency_ms = Math.round(performance.now() - t0)
  const text = await res.text()
  if (!res.ok) {
    return { ok: false, status: res.status, latency_ms, errorText: text }
  }
  const body = text ? (JSON.parse(text) as T) : (undefined as T)
  return { ok: true, status: res.status, latency_ms, body }
}

function randSessionId(): string {
  return `smoke-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function randUser(): string {
  return `smoke-${Math.random().toString(36).slice(2, 8)}@receipt.test`
}

// Best-effort mint. Backend auth_router may or may not be deployed; if mint
// 404s or 405s we proceed without Authorization (current v0 endpoints don't
// enforce auth). If mint succeeds we attach the rcpt_ token on subsequent
// calls so this smoke page stays green once auth gets enforced.
async function bestEffortMintToken(user: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/hook-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, label: "smoke-test" }),
    })
    if (!res.ok) return null
    const body = (await res.json()) as { token?: string }
    return body.token ?? null
  } catch {
    return null
  }
}

export function SmokePage() {
  const [rows, setRows] = useState<Row[]>(INITIAL_ROWS)
  const [running, setRunning] = useState(false)
  const [meta, setMeta] = useState<string>("")

  const setRow = useCallback((i: number, patch: Partial<Row>) => {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }, [])

  const run = useCallback(async () => {
    setRunning(true)
    setRows(INITIAL_ROWS.map((r) => ({ ...r })))

    const user = randUser()
    const sessionId = randSessionId()
    const token = await bestEffortMintToken(user)
    setMeta(`user=${user} · session_id=${sessionId} · auth=${token ? "rcpt_token" : "none"}`)

    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }

    // 1. POST /sessions/events — synthetic batch: 3 events for one new session
    setRow(0, { status: "running" })
    const ts = new Date().toISOString()
    const ingest = await timedFetch<{ accepted: number; session_ids: string[] }>(
      "/sessions/events",
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          events: [
            {
              session_id: sessionId,
              user,
              kind: "tool_use",
              ts,
              tool: "Bash",
              content: "echo smoke",
              tokens_input: 12,
              tokens_output: 8,
              cost_usd: 0.001,
            },
            {
              session_id: sessionId,
              user,
              kind: "file_change",
              ts,
              path: "src/smoke.ts",
            },
            {
              session_id: sessionId,
              user,
              kind: "error",
              ts,
              content: "synthetic error from smoke page",
            },
          ],
        }),
      },
    )
    if (!ingest.ok) {
      setRow(0, { status: "fail", latency_ms: ingest.latency_ms, error: (ingest.errorText ?? "").slice(0, 200) })
      setRunning(false)
      return
    }
    setRow(0, { status: "ok", latency_ms: ingest.latency_ms, note: `accepted=${ingest.body?.accepted}` })

    // 2. GET /sessions
    setRow(1, { status: "running" })
    const list = await timedFetch<{ items: unknown[]; total: number }>(
      "/sessions",
      { method: "GET", headers },
    )
    if (!list.ok) {
      setRow(1, { status: "fail", latency_ms: list.latency_ms, error: (list.errorText ?? "").slice(0, 200) })
    } else {
      setRow(1, { status: "ok", latency_ms: list.latency_ms, note: `total=${list.body?.total}` })
    }

    // 3. GET /sessions/{id}
    setRow(2, { status: "running", path: `/sessions/${sessionId}` })
    const detail = await timedFetch<{ events: unknown[] }>(
      `/sessions/${sessionId}`,
      { method: "GET", headers },
    )
    if (!detail.ok) {
      setRow(2, { status: "fail", latency_ms: detail.latency_ms, error: (detail.errorText ?? "").slice(0, 200) })
    } else {
      setRow(2, { status: "ok", latency_ms: detail.latency_ms, note: `events=${detail.body?.events?.length ?? 0}` })
    }

    // 4. POST /sessions/{id}/summary
    setRow(3, { status: "running", path: `/sessions/${sessionId}/summary` })
    const gen = await timedFetch<{ summary: string }>(
      `/sessions/${sessionId}/summary`,
      { method: "POST", headers },
    )
    if (!gen.ok) {
      setRow(3, { status: "fail", latency_ms: gen.latency_ms, error: (gen.errorText ?? "").slice(0, 200) })
    } else {
      setRow(3, { status: "ok", latency_ms: gen.latency_ms })
    }

    // 5. GET /sessions/{id}/summary
    setRow(4, { status: "running", path: `/sessions/${sessionId}/summary` })
    const getSum = await timedFetch<{ summary: string }>(
      `/sessions/${sessionId}/summary`,
      { method: "GET", headers },
    )
    if (!getSum.ok) {
      setRow(4, { status: "fail", latency_ms: getSum.latency_ms, error: (getSum.errorText ?? "").slice(0, 200) })
    } else {
      setRow(4, { status: "ok", latency_ms: getSum.latency_ms })
    }

    // 6. GET /sessions/{id}/trail — 404 is expected until sibling task ships
    setRow(5, { status: "running", path: `/sessions/${sessionId}/trail` })
    const trail = await timedFetch<unknown>(
      `/sessions/${sessionId}/trail`,
      { method: "GET", headers },
    )
    if (trail.ok) {
      setRow(5, { status: "ok", latency_ms: trail.latency_ms })
    } else if (trail.status === 404) {
      setRow(5, { status: "pending", latency_ms: trail.latency_ms, note: "endpoint not shipped (404)" })
    } else {
      setRow(5, { status: "fail", latency_ms: trail.latency_ms, error: (trail.errorText ?? "").slice(0, 200) })
    }

    setRunning(false)
  }, [setRow])

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-3xl p-6 font-mono">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-lg uppercase tracking-wider text-ink-muted">Yoru smoke · /__smoke</h1>
          <button
            onClick={() => void run()}
            disabled={running}
            className="rounded-sm border border-rule bg-surface px-3 py-1 text-caption uppercase tracking-wider text-ink hover:bg-sunken disabled:opacity-50"
          >
            {running ? "running…" : "Run smoke"}
          </button>
        </div>

        <p className="mb-1 text-caption text-ink-muted">
          Live round-trip of every backend route. Bypasses VITE_USE_MOCKS.
        </p>
        {meta && <p className="mb-4 text-caption text-ink-faint break-all">{meta}</p>}

        {rows.every((r) => r.status === "idle") && !running ? (
          <EmptyState
            heading="No probes ran yet"
            body="Kick off a round-trip against every backend route."
            action={
              <button
                type="button"
                onClick={() => void run()}
                className="rounded-sm border border-rule bg-surface px-3 py-1 font-mono text-caption uppercase tracking-wider text-ink hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
              >
                Run smoke
              </button>
            }
          />
        ) : (
        <ol className="space-y-1">
          {rows.map((r, i) => (
            <li
              key={i}
              className="grid grid-cols-[1.5rem_3.5rem_1fr_auto] items-start gap-2 border-b border-dashed border-rule py-2 text-sm"
            >
              <span aria-hidden className="pt-0.5">
                {r.status === "ok" && <span className="text-emerald-600">✓</span>}
                {r.status === "fail" && <span className="text-red-600">✗</span>}
                {r.status === "pending" && <span className="text-amber-600">…</span>}
                {r.status === "running" && <span className="text-ink-muted">·</span>}
                {r.status === "idle" && <span className="text-ink-faint">·</span>}
              </span>
              <span className="pt-0.5 text-caption uppercase text-ink-muted">{r.method}</span>
              <div className="flex flex-col gap-0.5">
                <span className="text-ink">{r.path}</span>
                <span className="text-caption text-ink-muted">{r.label}</span>
                {r.note && <span className="text-caption text-ink-muted">{r.note}</span>}
                {r.error && (
                  <pre className="whitespace-pre-wrap break-all text-caption text-red-700">{r.error}</pre>
                )}
              </div>
              <span className="pt-0.5 text-caption text-ink-muted">
                {r.status === "running" ? (
                  <span
                    role="status"
                    aria-label="Probe running"
                    className="inline-block h-3 w-10 rounded-sm bg-sunken/60 motion-safe:animate-pulse"
                  />
                ) : r.latency_ms !== undefined ? `${r.latency_ms}ms` : ""}
              </span>
            </li>
          ))}
        </ol>
        )}
      </div>
    </div>
  )
}
