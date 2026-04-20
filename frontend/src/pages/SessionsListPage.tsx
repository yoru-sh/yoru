import { useQuery, useQueryClient } from "@tanstack/react-query"
import { listSessions } from "../lib/api"
import { FilterBar } from "../features/sessions/FilterBar"
import { useFilters } from "../features/sessions/filters"
import {
  SessionsTable,
  SessionsTableSkeleton,
} from "../features/sessions/SessionsTable"
import type { SessionList } from "../types/receipt"

export function SessionsListPage() {
  const filters = useFilters()
  const queryClient = useQueryClient()

  const query = useQuery<SessionList>({
    queryKey: ["sessions", filters],
    queryFn: () => listSessions(filters),
  })

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between gap-4">
        <h1 className="font-mono text-lg font-semibold text-ink">Sessions</h1>
        {query.isSuccess && (
          <span className="font-mono text-caption text-ink-muted">
            {query.data.total} {query.data.total === 1 ? "session" : "sessions"}
          </span>
        )}
      </header>

      <FilterBar />

      {query.isPending ? (
        <SessionsTableSkeleton />
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
      className="flex items-center justify-between gap-4 rounded border border-flag-env bg-flag-env-bg px-4 py-3 text-flag-env-fg"
    >
      <div className="font-mono text-caption">
        <span className="font-semibold">Couldn't load sessions.</span>{" "}
        <span className="opacity-80">{message}</span>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-sm border border-flag-env-fg/40 px-2 py-1 font-mono text-micro uppercase tracking-wider hover:bg-flag-env/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
      >
        Retry
      </button>
    </div>
  )
}

