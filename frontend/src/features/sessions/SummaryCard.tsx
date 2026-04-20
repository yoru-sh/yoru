import { useQuery } from "@tanstack/react-query"
import { getSummary } from "../../lib/api"
import { formatRelative } from "../../lib/format"
import type { Summary } from "../../types/receipt"
import { Skeleton } from "../../components/ui/Skeleton"

interface SummaryCardProps {
  sessionId: string
}

export function SummaryCard({ sessionId }: SummaryCardProps) {
  const query = useQuery<Summary>({
    queryKey: ["session", sessionId, "summary"],
    queryFn: () => getSummary(sessionId),
  })

  return (
    <section aria-label="Session summary" className="px-4 py-4">
      {query.isPending ? (
        <SummarySkeleton />
      ) : query.isError ? (
        <p role="alert" className="font-mono text-caption text-flag-env-fg">
          <span className="mr-1 font-semibold">[ERR]</span>
          Couldn&apos;t load summary.
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
    <div role="status" aria-label="Loading summary" className="space-y-2">
      <Skeleton.Line decorative className="w-3/4" />
      <Skeleton.Line decorative className="w-full" />
      <Skeleton.Line decorative className="w-2/3" />
    </div>
  )
}

function prettyModel(id: string): string {
  if (id.includes("haiku-4-5")) return "Haiku 4.5"
  if (id.includes("sonnet-4-6")) return "Sonnet 4.6"
  if (id.includes("opus-4-7")) return "Opus 4.7"
  return id
}
