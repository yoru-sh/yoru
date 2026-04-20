import { useMutation, useQueryClient } from "@tanstack/react-query"
import { postSummary } from "../../lib/api"
import { formatCost, formatDuration, formatRelative } from "../../lib/format"
import { toast } from "../../components/Toaster"
import { RedFlagBadge } from "./RedFlagBadge"
import type { SessionDetail } from "../../types/receipt"

interface SessionHeroProps {
  session: SessionDetail
}

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

export function SessionHero({ session }: SessionHeroProps) {
  const shortId = session.id.slice(0, 4)
  const summary = (session.summary ?? "").trim()

  return (
    <header className="rounded-sm border border-rule bg-surface">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-dashed border-rule px-4 py-2">
        <p className={RUBRIC}>
          RECEIPT · SESSION {shortId} ·{" "}
          <time dateTime={session.started_at} title={session.started_at}>
            {formatRelative(session.started_at)}
          </time>
        </p>
        <p className={`${RUBRIC} tabular-nums`}>{session.started_at}</p>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3 sm:grid-cols-5">
        <Stat label="user">
          <span className="font-mono text-sm text-ink truncate block" title={session.user_email}>
            {session.user_email}
          </span>
        </Stat>
        <Stat label="duration">
          <span className="font-mono text-sm text-ink tabular-nums">
            {formatDuration(session.duration_ms)}
          </span>
        </Stat>
        <Stat label="cost">
          <span className="font-mono text-sm text-ink tabular-nums">
            {formatCost(session.cost_usd)}
          </span>
        </Stat>
        <Stat label="tools">
          <span className="font-mono text-sm text-ink tabular-nums">{session.tool_count}</span>
        </Stat>
        <Stat label="flags">
          {session.flags.length === 0 ? (
            <span className="font-mono text-sm text-ink-faint tabular-nums">0</span>
          ) : (
            <div className="flex flex-wrap items-center gap-1">
              {session.flags.map((kind) => (
                <RedFlagBadge key={kind} kind={kind} />
              ))}
            </div>
          )}
        </Stat>
      </dl>

      <div className="border-t border-dashed border-rule px-4 py-3">
        <p className={`${RUBRIC} mb-1.5`}>Summary</p>
        {summary ? (
          <p className="font-sans text-sm leading-relaxed text-ink line-clamp-3">{summary}</p>
        ) : (
          <GenerateSummary sessionId={session.id} />
        )}
      </div>
    </header>
  )
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className={RUBRIC}>{label}</dt>
      <dd className="mt-1 min-w-0">{children}</dd>
    </div>
  )
}

function GenerateSummary({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => postSummary(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] })
      queryClient.invalidateQueries({ queryKey: ["session", sessionId, "summary"] })
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error("Couldn't generate summary", msg)
    },
  })

  if (mutation.isPending) {
    return (
      <div role="status" aria-label="Generating summary" className="space-y-2">
        <div aria-hidden className="h-4 w-3/4 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        <div aria-hidden className="h-4 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        <div aria-hidden className="h-4 w-2/3 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="font-sans text-sm text-ink-muted">
        No summary generated yet. Haiku 4.5 will draft one from this session&apos;s events.
      </p>
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-rule px-3 py-1 font-sans text-caption text-ink hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-60"
      >
        Generate summary
      </button>
    </div>
  )
}
