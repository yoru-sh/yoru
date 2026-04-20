import { supabase } from "./supabase"
import type {
  Filters,
  SessionDetail,
  SessionList,
  Summary,
} from "../types/receipt"
import { mockListSessions, mockGetSession, mockGetSummary } from "../mocks/sessions"
import { toast } from "../components/Toaster"

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "1"
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8002/api/v1"

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`)
  }
}

let tokenExpiredHandled = false

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await supabase.auth.getSession()
  const wasAuthenticated = !!data.session
  const headers = new Headers(init?.headers)
  if (data.session) headers.set("Authorization", `Bearer ${data.session.access_token}`)
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json")

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const text = await res.text()
  if (!res.ok) {
    if (res.status === 401 && wasAuthenticated && !tokenExpiredHandled) {
      tokenExpiredHandled = true
      void supabase.auth.signOut().finally(() => {
        window.location.assign("/signin?reason=token-expired")
      })
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

// Server-side failures (5xx + network unreachable) toast; client errors (4xx)
// don't — those are routed by existing banner state. 401 is handled upstream
// by apiFetch's signOut latch.
function notifyServerError(err: unknown): void {
  if (err instanceof ApiError) {
    if (err.status >= 500 && err.status < 600) {
      toast.error("Couldn't load sessions", err.message)
    }
    return
  }
  const detail = err instanceof Error ? err.message : String(err)
  toast.error("Couldn't load sessions", detail)
}

export async function listSessions(filters: Filters): Promise<SessionList> {
  if (USE_MOCKS) return mockListSessions(filters)
  try {
    return await apiFetch<SessionList>(`/sessions${qs(filters) ? `?${qs(filters)}` : ""}`)
  } catch (err) {
    notifyServerError(err)
    throw err
  }
}

export async function getSession(id: string): Promise<SessionDetail> {
  if (USE_MOCKS) return mockGetSession(id)
  try {
    return await apiFetch<SessionDetail>(`/sessions/${id}`)
  } catch (err) {
    notifyServerError(err)
    throw err
  }
}

export async function getSummary(id: string): Promise<Summary> {
  if (USE_MOCKS) return mockGetSummary(id)
  try {
    return await apiFetch<Summary>(`/sessions/${id}/summary`)
  } catch (err) {
    notifyServerError(err)
    throw err
  }
}
