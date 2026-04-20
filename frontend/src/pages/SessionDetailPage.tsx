import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ApiError, getSession } from "../lib/api"
import { formatCost, formatDuration, formatRelative } from "../lib/format"
import type { SessionDetail } from "../types/receipt"
import { RedFlagBadge } from "../features/sessions/RedFlagBadge"
import { RedFlagLegend } from "../features/sessions/RedFlagLegend"
import { SummaryCard } from "../features/sessions/SummaryCard"
import { Timeline } from "../features/sessions/Timeline"
import { FilesChangedAccordion } from "../features/sessions/FilesChangedAccordion"

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [legendOpen, setLegendOpen] = useState(false)

  const query = useQuery<SessionDetail>({
    queryKey: ["session", id],
    queryFn: () => getSession(id as string),
    enabled: Boolean(id),
  })

  if (!id) return <NotFound />

  return (
    <div className="space-y-5">
      <nav className="font-mono text-micro uppercase tracking-wider text-ink-faint">
        <Link to="/" className="hover:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500">
          ← All sessions
        </Link>
      </nav>

      {query.isPending ? (
        <DetailSkeleton />
      ) : query.isError ? (
        isNotFound(query.error) ? (
          <NotFoundState />
        ) : (
          <ErrorBanner
            message={query.error instanceof Error ? query.error.message : "Failed to load session."}
            onRetry={() => queryClient.invalidateQueries({ queryKey: ["session", id] })}
          />
        )
      ) : (
        <>
          <Header session={query.data} onFlagClick={() => setLegendOpen(true)} />
          <SummaryCard sessionId={id} />
          <Timeline events={query.data.events} onFlagClick={() => setLegendOpen(true)} />
          <FilesChangedAccordion files={query.data.files_changed} />
        </>
      )}

      <RedFlagLegend open={legendOpen} onClose={() => setLegendOpen(false)} />
    </div>
  )
}

interface HeaderProps {
  session: SessionDetail
  onFlagClick: () => void
}

function Header({ session, onFlagClick }: HeaderProps) {
  const running = session.ended_at === null
  return (
    <header className="rounded border border-rule bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="font-mono text-lg font-semibold text-ink" title={session.id}>
          {session.user_email}
        </h1>
        <span className="font-mono text-caption text-ink-muted" title={session.started_at}>
          {formatRelative(session.started_at)}
        </span>
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 font-mono text-caption">
        <Stat label="duration">
          {running ? (
            <span className="italic text-accent-500">running…</span>
          ) : (
            <span className="text-ink">{formatDuration(session.duration_ms)}</span>
          )}
        </Stat>
        <Stat label="tools">
          <span className="tabular-nums text-ink">{session.tool_count}</span>
        </Stat>
        <Stat label="cost">
          <span className="tabular-nums text-ink">{formatCost(session.cost_usd)}</span>
        </Stat>
        <Stat label="session">
          <code className="rounded-sm bg-sunken px-1.5 py-0.5 text-ink-muted">{session.id}</code>
        </Stat>
      </dl>
      {session.flags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {session.flags.map((flag) => (
            <RedFlagBadge key={flag} kind={flag} onClick={onFlagClick} />
          ))}
        </div>
      )}
    </header>
  )
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-micro uppercase tracking-wider text-ink-faint">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-5" aria-hidden="true" role="status" aria-label="Loading session">
      <header className="rounded border border-rule bg-surface p-4">
        <div className="h-5 w-56 animate-pulse rounded-sm bg-sunken" />
        <div className="mt-4 flex flex-wrap gap-4">
          <div className="h-3 w-24 animate-pulse rounded-sm bg-sunken" />
          <div className="h-3 w-20 animate-pulse rounded-sm bg-sunken" />
          <div className="h-3 w-20 animate-pulse rounded-sm bg-sunken" />
          <div className="h-3 w-40 animate-pulse rounded-sm bg-sunken" />
        </div>
      </header>
      <section className="rounded border border-rule bg-surface p-4">
        <ol className="relative space-y-4 before:absolute before:left-3 before:top-1 before:bottom-1 before:w-px before:bg-rule">
          {[0, 1, 2].map((i) => (
            <li key={i} className="flex items-start gap-3 pl-6">
              <div className="h-3 w-full max-w-[28rem] animate-pulse rounded-sm bg-sunken" />
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

function isNotFound(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 404
  if (err instanceof Error) return /not found/i.test(err.message)
  return false
}

function NotFoundState() {
  return (
    <div className="rounded border border-dashed border-rule bg-surface px-6 py-12 text-center">
      <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">
        Receipt not found
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        This session id doesn't match any receipt.{" "}
        <Link
          to="/"
          className="text-accent-500 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        >
          Back to all sessions
        </Link>
        .
      </p>
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
        <span className="font-semibold">Couldn't load session.</span>{" "}
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

function NotFound() {
  return (
    <div className="rounded border border-dashed border-rule bg-surface px-6 py-12 text-center">
      <p className="font-mono text-caption text-ink">Session id missing.</p>
    </div>
  )
}
