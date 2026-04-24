import { formatDuration, formatRelative } from "./format"
import { RedFlagBadge } from "./RedFlagBadge"
import type { SessionDetail } from "./types"

interface SessionHeroViewProps {
  session: SessionDetail
  onExport?: () => void
  isExporting?: boolean
  onGenerateSummary?: () => void
  isGeneratingSummary?: boolean
}

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

export function SessionHeroView({
  session,
  onExport,
  isExporting = false,
  onGenerateSummary,
  isGeneratingSummary = false,
}: SessionHeroViewProps) {
  const shortId = session.id.slice(0, 4)
  const summary = (session.summary ?? "").trim()
  // Token breakdown hidden pre-launch — see ROADMAP.md. Kept as a named
  // constant so re-enabling is a one-line render change.
  // const usage = session.usage_events ?? []
  // const newWork = ... (compute freshIn + cacheWrite + output from usage)

  return (
    <header className="rounded-sm border border-rule bg-surface">
      <div className="px-4 py-4 border-b border-dashed border-rule">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1
            className="font-sans text-2xl font-semibold text-ink min-w-0 break-words"
            title={session.title ?? session.id}
          >
            {session.title ?? session.user_email}
          </h1>
          {onExport && (
            <div className="ml-auto shrink-0">
              <button
                type="button"
                onClick={onExport}
                disabled={isExporting}
                title="Download full audit trail (JSON)"
                className={
                  "inline-flex items-center gap-1 rounded-sm border border-rule px-2 py-1 " +
                  "font-mono text-caption uppercase tracking-wider text-ink-muted " +
                  "hover:bg-sunken hover:text-ink " +
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
                  "focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
                  "disabled:opacity-60"
                }
              >
                {isExporting ? "…" : "↓ export trail"}
              </button>
            </div>
          )}
        </div>
        <p className={`${RUBRIC} mt-2 flex flex-wrap items-baseline gap-x-2`}>
          <span className="font-mono normal-case tracking-normal text-ink-muted">
            {session.user_email}
          </span>
          <span aria-hidden className="text-ink-faint">·</span>
          <span>session {shortId}</span>
          <span aria-hidden className="text-ink-faint">·</span>
          <time
            dateTime={session.started_at}
            title={session.started_at}
            className="tabular-nums"
          >
            {formatRelative(session.started_at)}
          </time>
        </p>
        {session.flags.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {session.flags.map((kind) => (
              <RedFlagBadge key={kind} kind={kind} />
            ))}
          </div>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3">
        <Stat label="duration">
          <span className="font-mono text-sm text-ink tabular-nums">
            {formatDuration(session.duration_ms)}
          </span>
        </Stat>
        <Stat label="tools">
          <span className="font-mono text-sm text-ink tabular-nums">{session.tool_count}</span>
        </Stat>
        {/* tokens and cost stats hidden pre-launch (see ROADMAP.md) —
            same decision as TokenPanel. Data keeps flowing from the
            backend; only the UI surface is hidden. */}
      </dl>

      <div className="border-t border-dashed border-rule px-4 py-3">
        <p className={`${RUBRIC} mb-1.5`}>§ Summary · Haiku 4.5</p>
        {summary ? (
          <p className="font-sans text-sm leading-relaxed text-ink">{summary}</p>
        ) : isGeneratingSummary ? (
          <div role="status" aria-label="Generating summary" className="space-y-2">
            <div aria-hidden className="h-4 w-3/4 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
            <div aria-hidden className="h-4 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
            <div aria-hidden className="h-4 w-2/3 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
          </div>
        ) : onGenerateSummary ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-sans text-sm text-ink-muted">
              No summary generated yet. Haiku 4.5 will draft one from this session&apos;s events.
            </p>
            <button
              type="button"
              onClick={onGenerateSummary}
              className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-rule px-3 py-1 font-sans text-caption text-ink hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
            >
              Generate summary
            </button>
          </div>
        ) : (
          <p className="font-sans text-sm text-ink-muted">No summary yet.</p>
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
