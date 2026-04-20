import { memo } from "react"
import { Link } from "react-router-dom"
import type { Session } from "../../types/receipt"
import { formatCost, formatDuration, formatRelative } from "../../lib/format"
import { RedFlagBadge } from "./RedFlagBadge"

interface SessionRowProps {
  session: Session
  gridCols: string
}

const cellCls = "px-3 py-2 min-w-0"

function SessionRowImpl({ session, gridCols }: SessionRowProps) {
  const running = session.ended_at === null
  return (
    <Link
      to={`/s/${session.id}`}
      aria-label={`Session by ${session.user_email}, started ${formatRelative(session.started_at)}`}
      className={
        "block hover:bg-sunken " +
        gridCols + " " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
        "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
      }
    >
      <div className={cellCls + " truncate font-mono text-caption text-ink"} title={session.user_email}>
        {session.user_email}
      </div>
      <div className={cellCls + " font-mono text-caption text-ink-muted"} title={session.started_at}>
        {formatRelative(session.started_at)}
      </div>
      <div className={cellCls + " font-mono text-caption tabular-nums"}>
        {running ? (
          <span className="italic text-accent-500">running…</span>
        ) : (
          <span className="text-ink-muted">{formatDuration(session.duration_ms)}</span>
        )}
      </div>
      <div className={cellCls + " font-mono text-caption tabular-nums text-ink-muted"}>
        {session.tool_count}
      </div>
      <div className={cellCls + " font-mono text-caption tabular-nums text-ink"}>
        {formatCost(session.cost_usd)}
      </div>
      <div className={cellCls}>
        {session.flags.length === 0 ? (
          <span className="font-mono text-caption text-ink-faint">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {session.flags.map((flag) => (
              <RedFlagBadge key={flag} kind={flag} />
            ))}
          </div>
        )}
      </div>
    </Link>
  )
}

export const SessionRow = memo(SessionRowImpl)
