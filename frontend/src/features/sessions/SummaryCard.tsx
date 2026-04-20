import { useQuery } from "@tanstack/react-query"
import { getSummary } from "../../lib/api"
import { formatRelative } from "../../lib/format"
import type { Summary } from "../../types/receipt"

interface SummaryCardProps {
  sessionId: string
}

export function SummaryCard({ sessionId }: SummaryCardProps) {
  const query = useQuery<Summary>({
    queryKey: ["session", sessionId, "summary"],
    queryFn: () => getSummary(sessionId),
  })

  return (
    <section
      aria-label="Session summary"
      className="rounded border border-rule bg-surface p-4"
    >
      {query.isPending ? (
        <SummarySkeleton />
      ) : query.isError ? (
        <p className="font-mono text-caption text-flag-env-fg">
          Couldn't load summary.
        </p>
      ) : (
        <>
          <p className="text-sm leading-relaxed text-ink">{query.data.text}</p>
          <p className="mt-3 font-mono text-micro uppercase tracking-wider text-ink-faint">
            via {prettyModel(query.data.model)} · cached {formatRelative(query.data.cached_at)}
          </p>
        </>
      )}
    </section>
  )
}

function SummarySkeleton() {
  return (
    <div className="space-y-2" aria-hidden="true">
      <div className="h-3 w-11/12 animate-pulse rounded-sm bg-sunken" />
      <div className="h-3 w-10/12 animate-pulse rounded-sm bg-sunken" />
      <div className="h-3 w-8/12 animate-pulse rounded-sm bg-sunken" />
      <div className="mt-3 h-2.5 w-44 animate-pulse rounded-sm bg-sunken" />
    </div>
  )
}

function prettyModel(id: string): string {
  if (id.includes("haiku-4-5")) return "Haiku 4.5"
  if (id.includes("sonnet-4-6")) return "Sonnet 4.6"
  if (id.includes("opus-4-7")) return "Opus 4.7"
  return id
}
