import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch, ApiError } from "../../lib/api"

type NotifType = "info" | "success" | "warning" | "error"

interface Notification {
  id: string
  type: NotifType
  title: string
  message: string
  action_url?: string | null
  is_read: boolean
  created_at: string
}

interface NotificationListResponse {
  items: Notification[]
  total: number
}

const UNREAD_KEY = ["me", "notifications", "unread"] as const
const LIST_KEY   = ["me", "notifications", "list"] as const

async function fetchUnreadCount(): Promise<number> {
  try {
    const r = await apiFetch<{ count: number } | number>(
      "/me/notifications/unread/count",
    )
    return typeof r === "number" ? r : (r?.count ?? 0)
  } catch (err) {
    if (err instanceof ApiError) return 0
    return 0
  }
}

async function fetchList(): Promise<Notification[]> {
  try {
    const r = await apiFetch<NotificationListResponse | Notification[]>(
      "/me/notifications?page=1&page_size=10",
    )
    return Array.isArray(r) ? r : (r?.items ?? [])
  } catch {
    return []
  }
}

async function markRead(id: string): Promise<void> {
  await apiFetch<void>(`/me/notifications/${id}/read`, { method: "PATCH" })
}

async function markAllRead(): Promise<void> {
  await apiFetch<void>(`/me/notifications/read-all`, { method: "PATCH" })
}

async function deleteOne(id: string): Promise<void> {
  await apiFetch<void>(`/me/notifications/${id}`, { method: "DELETE" })
}

const TYPE_DOT: Record<NotifType, string> = {
  info:    "bg-ink-muted",
  success: "bg-op-create",
  warning: "bg-flag-migration",
  error:   "bg-flag-env",
}

function relativeTime(iso: string): string {
  const now = Date.now()
  const t = new Date(iso).getTime()
  const d = Math.max(0, now - t)
  const s = Math.round(d / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: unreadCount = 0 } = useQuery({
    queryKey: UNREAD_KEY,
    queryFn: fetchUnreadCount,
    refetchInterval: 30_000,
    staleTime: 10_000,
    retry: 0,
    meta: { silent: true },
  })

  const { data: items = [] } = useQuery({
    queryKey: LIST_KEY,
    queryFn: fetchList,
    enabled: open,
    staleTime: 5_000,
    retry: 0,
    meta: { silent: true },
  })

  const readOne = useMutation({
    mutationFn: markRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: UNREAD_KEY })
      qc.invalidateQueries({ queryKey: LIST_KEY })
    },
  })

  const readAll = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: UNREAD_KEY })
      qc.invalidateQueries({ queryKey: LIST_KEY })
    },
  })

  const deleteNotif = useMutation({
    mutationFn: deleteOne,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: UNREAD_KEY })
      qc.invalidateQueries({ queryKey: LIST_KEY })
    },
  })

  const clearAll = useMutation({
    mutationFn: async () => {
      // No server-side bulk delete — iterate locally loaded items.
      await Promise.all(items.map((n) => deleteOne(n.id)))
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: UNREAD_KEY })
      qc.invalidateQueries({ queryKey: LIST_KEY })
    },
  })

  function onClickNotif(n: Notification) {
    if (!n.is_read) readOne.mutate(n.id)
    if (n.action_url) {
      setOpen(false)
      navigate(n.action_url)
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={`Notifications — ${unreadCount} unread`}
        onClick={() => setOpen((v) => !v)}
        className="relative inline-flex h-7 w-7 items-center justify-center rounded-sm border border-rule text-ink-muted hover:bg-sunken hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="h-4 w-4">
          <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            className="absolute -right-1 -top-1 flex h-3.5 min-w-[0.875rem] items-center justify-center rounded-full bg-flag-env px-1 font-mono text-[0.625rem] font-semibold text-paper"
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            role="menu"
            aria-label="Notifications"
            className="absolute right-0 top-9 z-50 w-80 rounded border border-rule bg-surface shadow-md"
          >
            <div className="flex items-center justify-between border-b border-rule px-3 py-2">
              <p className="font-mono text-caption uppercase tracking-wider text-ink-faint">
                Notifications
              </p>
              <div className="flex items-center gap-3">
                {unreadCount > 0 && (
                  <button
                    type="button"
                    onClick={() => readAll.mutate()}
                    disabled={readAll.isPending}
                    className="font-mono text-caption text-ink-muted hover:text-ink disabled:opacity-60"
                  >
                    Mark all read
                  </button>
                )}
                {items.length > 0 && (
                  <button
                    type="button"
                    onClick={() => clearAll.mutate()}
                    disabled={clearAll.isPending}
                    className="font-mono text-caption text-flag-env-fg hover:underline disabled:opacity-60"
                  >
                    {clearAll.isPending ? "Clearing…" : "Clear all"}
                  </button>
                )}
              </div>
            </div>
            <ul className="max-h-96 overflow-y-auto">
              {items.length === 0 ? (
                <li className="px-4 py-6 text-center text-caption text-ink-faint">
                  No notifications
                </li>
              ) : (
                items.map((n) => (
                  <li
                    key={n.id}
                    className="group relative border-b border-dashed border-rule last:border-b-0"
                  >
                    <button
                      type="button"
                      onClick={() => onClickNotif(n)}
                      className={
                        "flex w-full items-start gap-2 px-3 py-3 pr-9 text-left hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
                        (n.is_read ? "opacity-60" : "")
                      }
                    >
                      <span
                        aria-hidden="true"
                        className={
                          "mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full " +
                          TYPE_DOT[n.type]
                        }
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="truncate text-sm font-semibold text-ink">{n.title}</p>
                          <span className="shrink-0 font-mono text-micro text-ink-faint">
                            {relativeTime(n.created_at)}
                          </span>
                        </div>
                        <p className="mt-0.5 text-caption text-ink-muted line-clamp-2">
                          {n.message}
                        </p>
                      </div>
                    </button>
                    <button
                      type="button"
                      aria-label="Dismiss"
                      title="Dismiss"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        deleteNotif.mutate(n.id)
                      }}
                      className="absolute right-2 top-2 inline-flex h-5 w-5 items-center justify-center rounded-sm text-ink-faint opacity-0 transition-opacity hover:bg-rule hover:text-ink focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 group-hover:opacity-100"
                    >
                      <span aria-hidden="true" className="font-mono text-sm leading-none">×</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
