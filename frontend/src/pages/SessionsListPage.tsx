import { useMemo } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { listSessions, listWorkspaces, type Workspace } from "../lib/api"
import { FilterBar } from "../features/sessions/FilterBar"
import { useFilters } from "../features/sessions/filters"
import { SessionsTable } from "../features/sessions/SessionsTable"
import { Skeleton } from "../components/ui/Skeleton"
import type { SessionList } from "../types/receipt"

const RUBRIC =
  "mt-1 font-mono text-caption uppercase tracking-wider text-ink-faint tabular-nums"

// Events are the sum of per-session tool calls — backend Session shape has no
// top-level event_count, and tool_call is the dominant event kind in practice.
function rubricFor(list: SessionList | undefined): string {
  if (!list) return "— sessions · — events"
  const sessions = list.total
  const events = list.items.reduce((n, s) => n + s.tool_count, 0)
  return `${sessions} ${sessions === 1 ? "session" : "sessions"} · ${events} ${events === 1 ? "event" : "events"}`
}

export function SessionsListPage() {
  const filters = useFilters()
  const queryClient = useQueryClient()

  const query = useQuery<SessionList>({
    queryKey: ["sessions", filters],
    queryFn: () => listSessions(filters),
  })

  const workspacesQuery = useQuery<Workspace[]>({
    queryKey: ["me", "workspaces"],
    queryFn: listWorkspaces,
    staleTime: 60_000,
    meta: { silent: true },
  })

  const workspaceNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const w of workspacesQuery.data ?? []) m.set(w.id, w.name)
    return m
  }, [workspacesQuery.data])

  return (
    <div className="space-y-4">
      <header className="border-b border-dashed border-rule pb-4">
        <h1 className="font-mono text-2xl font-semibold text-ink">Receipts</h1>
        <p className={RUBRIC}>{rubricFor(query.data)}</p>
      </header>

      <FilterBar />

      {query.isPending ? (
        <div role="status" aria-label="Loading sessions" className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton.ListRow key={i} decorative />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorBanner
          message={query.error instanceof Error ? query.error.message : "Failed to load sessions."}
          onRetry={() => queryClient.invalidateQueries({ queryKey: ["sessions"] })}
        />
      ) : (
        <SessionsTable
          sessions={query.data.items}
          workspaceNameById={workspaceNameById}
        />
      )}
    </div>
  )
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-sm border border-rule border-l-2 border-l-flag-env bg-surface px-3 py-2 text-sm text-ink"
    >
      <p className="flex-1">
        <span className="mr-2 font-mono text-ink-muted">[ERR]</span>
        <span>Couldn't load sessions. {message}</span>
      </p>
      <button
        type="button"
        onClick={onRetry}
        className={
          "shrink-0 rounded-sm border border-rule px-2 py-1 " +
          "font-mono text-micro uppercase tracking-wider text-ink-muted " +
          "hover:bg-sunken " +
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
          "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
        }
      >
        Retry
      </button>
    </div>
  )
}
