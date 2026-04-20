import { useQuery, useQueryClient } from "@tanstack/react-query"
import { listSessions } from "../lib/api"
import { FilterBar } from "../features/sessions/FilterBar"
import { useFilters } from "../features/sessions/filters"
import { SessionsTable } from "../features/sessions/SessionsTable"
import { Skeleton } from "../components/ui/Skeleton"
import type { SessionList } from "../types/receipt"

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

export function SessionsListPage() {
  const filters = useFilters()
  const queryClient = useQueryClient()

  const query = useQuery<SessionList>({
    queryKey: ["sessions", filters],
    queryFn: () => listSessions(filters),
  })

  const total = query.data?.total
  const countLabel = total === undefined ? "—" : String(total)
  const entriesLabel = total === 1 ? "entry" : "entries"

  return (
    <div className="space-y-4">
      <header className="rounded-sm border border-rule bg-surface">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-dashed border-rule px-4 py-2">
          <p className={RUBRIC}>RECEIPT · INDEX</p>
          <p className={`${RUBRIC} tabular-nums`}>
            {countLabel} {entriesLabel}
          </p>
        </div>
        <div className="px-4 py-3">
          <h1 className="font-mono text-2xl font-semibold text-ink">
            <span className="text-ink-muted">§</span> Sessions{" "}
            <span className="text-ink-faint">·</span>{" "}
            <span className="tabular-nums">{countLabel}</span>
          </h1>
        </div>
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
        <SessionsTable sessions={query.data.items} />
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
