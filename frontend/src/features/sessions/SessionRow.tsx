import { Link } from "react-router-dom"
import type { Session } from "../../types/receipt"
import { formatCost, formatDuration, formatRelative } from "../../lib/format"
import { RedFlagBadge } from "./RedFlagBadge"

interface SessionRowProps {
  session: Session
}

const cellCls = "px-3 py-2 align-middle"

export function SessionRow({ session }: SessionRowProps) {
  const running = session.ended_at === null

  return (
    <tr className="group border-b border-rule last:border-b-0 hover:bg-sunken">
      <td className={cellCls}>
        <Link
          to={`/s/${session.id}`}
          className="block truncate font-mono text-caption text-ink group-hover:text-accent-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          title={session.user_email}
          style={{ maxWidth: "32ch" }}
        >
          {session.user_email}
        </Link>
      </td>
      <td className={cellCls + " font-mono text-caption text-ink-muted"} title={session.started_at}>
        {formatRelative(session.started_at)}
      </td>
      <td className={cellCls + " font-mono text-caption"}>
        {running ? (
          <span className="italic text-accent-500">running…</span>
        ) : (
          <span className="text-ink-muted">{formatDuration(session.duration_ms)}</span>
        )}
      </td>
      <td className={cellCls + " font-mono text-caption tabular-nums text-ink-muted"}>
        {session.tool_count}
      </td>
      <td className={cellCls + " font-mono text-caption tabular-nums text-ink"}>
        {formatCost(session.cost_usd)}
      </td>
      <td className={cellCls}>
        {session.flags.length === 0 ? (
          <span className="font-mono text-caption text-ink-faint">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {session.flags.map((flag) => (
              <RedFlagBadge key={flag} kind={flag} />
            ))}
          </div>
        )}
      </td>
    </tr>
  )
}
