import { supabase } from "./supabase"
import type {
  Filters,
  SessionDetail,
  SessionList,
  Summary,
} from "../types/receipt"
import { mockListSessions, mockGetSession, mockGetSummary } from "../mocks/sessions"
import { queryClient } from "./queryClient"

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "1"
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8002/api/v1"

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`)
  }
}

// Billing plan lives here (not further down) because the 402 interceptor
// below must prime the shared ['orgs','me'] cache shape.
export type Plan = "free" | "team" | "org"

// Shared cache shape for ['orgs','me'] — single source of truth for the
// authenticated org's plan + quota state (US-V4-1 AC #6). Siblings
// (post-upgrade poll, plan badge) can widen as needed.
export interface OrgsMe {
  plan: Plan
  quota_exceeded: boolean
}

export const ORGS_ME_KEY = ["orgs", "me"] as const

let tokenExpiredHandled = false

const HOOK_TOKEN_KEY = "receipt.hook_token"
const HOOK_TOKEN_USER_KEY = "receipt.hook_token_user"

// Backend v0 accepts only `rcpt_*` tokens, not Supabase JWTs. Bridge: on first
// authenticated call, mint a rcpt_ via the unauthenticated POST /auth/hook-token
// endpoint (CLI-V0-DESIGN §5.1) and cache per-user in localStorage.
async function getHookToken(userEmail: string): Promise<string | null> {
  const cachedUser = localStorage.getItem(HOOK_TOKEN_USER_KEY)
  const cachedToken = localStorage.getItem(HOOK_TOKEN_KEY)
  if (cachedUser === userEmail && cachedToken) return cachedToken
  try {
    const res = await fetch(`${API_BASE}/auth/hook-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: userEmail, label: "web" }),
    })
    if (!res.ok) return null
    const body = (await res.json()) as { token?: string }
    if (!body.token) return null
    localStorage.setItem(HOOK_TOKEN_KEY, body.token)
    localStorage.setItem(HOOK_TOKEN_USER_KEY, userEmail)
    return body.token
  } catch {
    return null
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await supabase.auth.getSession()
  const wasAuthenticated = !!data.session
  const headers = new Headers(init?.headers)
  if (data.session) {
    const email = data.session.user?.email
    const hookToken = email ? await getHookToken(email) : null
    if (hookToken) headers.set("Authorization", `Bearer ${hookToken}`)
    else headers.set("Authorization", `Bearer ${data.session.access_token}`)
  }
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json")

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const text = await res.text()
  if (!res.ok) {
    if (res.status === 401 && wasAuthenticated && !tokenExpiredHandled) {
      // Invalidate cached hook token — next call will mint a fresh one before
      // the signOut loop. If it still 401s, fall through to the signout path.
      localStorage.removeItem(HOOK_TOKEN_KEY)
      localStorage.removeItem(HOOK_TOKEN_USER_KEY)
      tokenExpiredHandled = true
      void supabase.auth.signOut().finally(() => {
        window.location.assign("/signin?reason=token-expired")
      })
    }
    if (res.status === 402) {
      // Quota paywall — prime the ['orgs','me'] cache so <UpgradeBanner/>
      // renders without waiting for a /orgs/me refetch (US-V4-1 AC #6:
      // single source of truth).
      queryClient.setQueryData<OrgsMe | undefined>(
        ORGS_ME_KEY,
        (prev) => ({ plan: "free", ...prev, quota_exceeded: true }),
      )
    }
    throw new ApiError(res.status, text)
  }
  return text ? (JSON.parse(text) as T) : (undefined as T)
}

function qs(f: Filters): string {
  const p = new URLSearchParams()
  if (f.user) p.set("user", f.user)
  if (f.date_from) p.set("from_ts", f.date_from)
  if (f.date_to) p.set("to_ts", f.date_to)
  if (f.flag_only) p.set("flagged", "true")
  if (f.min_cost !== undefined) p.set("min_cost", String(f.min_cost))
  return p.toString()
}

// Backend returns `user`/`tools_count`/`ended_at` — frontend types use
// `user_email`/`tool_count`/`duration_ms`. Map on the way out.
interface RawSession {
  id: string
  user: string
  started_at: string
  ended_at: string | null
  tools_count: number
  cost_usd: number
  flags: string[]
}

function mapSession(r: RawSession): import("../types/receipt").Session {
  const start = Date.parse(r.started_at)
  const end = r.ended_at ? Date.parse(r.ended_at) : null
  const duration_ms = end && !isNaN(start) && !isNaN(end) ? end - start : 0
  return {
    id: r.id,
    user_email: r.user,
    started_at: r.started_at,
    ended_at: r.ended_at,
    duration_ms,
    tool_count: r.tools_count ?? 0,
    cost_usd: r.cost_usd ?? 0,
    flag_count: r.flags?.length ?? 0,
    flags: (r.flags ?? []) as import("../types/receipt").RedFlagKind[],
  }
}

export async function listSessions(filters: Filters): Promise<SessionList> {
  if (USE_MOCKS) return mockListSessions(filters)
  const raw = await apiFetch<{ items: RawSession[]; total?: number }>(
    `/sessions${qs(filters) ? `?${qs(filters)}` : ""}`,
  )
  return {
    items: (raw.items ?? []).map(mapSession),
    total: raw.total ?? (raw.items ?? []).length,
  }
}

interface RawEvent {
  id: number
  ts: string
  kind: string
  tool?: string | null
  path?: string | null
  content?: string | null
  output?: string | null
  flags?: string[]
}

interface RawSessionDetail extends RawSession {
  events: RawEvent[]
  files_changed?: Array<{ path: string; op: string; additions?: number; deletions?: number }>
  summary?: string | null
  tools_called?: string[]
}

function mapEventType(kind: string): import("../types/receipt").EventType {
  switch (kind) {
    case "tool_use":
    case "tool_call":
      return "tool_call"
    case "file_change":
      return "file_change"
    case "error":
      return "error"
    default:
      return "message"
  }
}

export async function getSession(id: string): Promise<SessionDetail> {
  if (USE_MOCKS) return mockGetSession(id)
  const raw = await apiFetch<RawSessionDetail>(`/sessions/${id}`)
  const base = mapSession(raw)
  return {
    ...base,
    events: (raw.events ?? [])
      // Filter out session_start/session_end — they are frame markers,
      // not user-visible timeline events.
      .filter((e) => e.kind !== "session_start" && e.kind !== "session_end")
      .map((e) => ({
        id: String(e.id),
        session_id: raw.id,
        at: e.ts,
        type: mapEventType(e.kind),
        tool_name: e.tool ?? undefined,
        file_path: e.path ?? undefined,
        text: e.content ?? undefined,
        output: e.output ?? undefined,
        flag: (e.flags && e.flags[0]) as import("../types/receipt").RedFlagKind | undefined,
      })),
    files_changed: (raw.files_changed ?? []).map((f) => ({
      path: f.path,
      op: (f.op ?? "edit") as import("../types/receipt").FileOp,
      additions: f.additions ?? 0,
      deletions: f.deletions ?? 0,
    })),
    summary: raw.summary ?? null,
  }
}

export async function postSummary(id: string): Promise<Summary> {
  if (USE_MOCKS) return mockGetSummary(id)
  return apiFetch<Summary>(`/sessions/${id}/summary`, { method: "POST" })
}

export async function getSummary(id: string): Promise<Summary> {
  if (USE_MOCKS) return mockGetSummary(id)
  return apiFetch<Summary>(`/sessions/${id}/summary`)
}

// Billing — mirror of C1 backend shapes (BILLING-PLANS-V1.md §3).
// (`Plan`, `OrgsMe`, `ORGS_ME_KEY` are declared near the top so the 402
// interceptor in apiFetch can reference them.)

export interface CheckoutRequest {
  plan: Plan
  success_url: string
  cancel_url: string
}

export interface CheckoutResponse {
  checkout_url: string
  session_id: string
}

export async function postCheckoutSession(plan: Plan): Promise<CheckoutResponse> {
  const body: CheckoutRequest = {
    plan,
    success_url: window.location.origin + "/settings/billing?upgraded=1",
    cancel_url: window.location.href,
  }
  if (USE_MOCKS) {
    return {
      checkout_url: "/settings/billing?upgraded=1&mock=1",
      session_id: "cs_mock_frontend",
    }
  }
  return apiFetch<CheckoutResponse>("/billing/checkout-session", {
    method: "POST",
    body: JSON.stringify(body),
  })
}
