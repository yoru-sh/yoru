import type { Session } from "../../types/receipt"
import { SessionRow } from "./SessionRow"

interface SessionsTableProps {
  sessions: Session[]
}

const headerCls =
  "px-3 py-2 text-left font-mono text-micro uppercase tracking-wider text-ink-faint"

export function SessionsTable({ sessions }: SessionsTableProps) {
  if (sessions.length === 0) return <SessionsTableEmpty />
  return (
    <div className="overflow-x-auto rounded border border-rule bg-surface">
      <table className="min-w-full border-collapse">
        <thead className="border-b border-rule bg-sunken/60">
          <tr>
            <th className={headerCls} scope="col">User</th>
            <th className={headerCls} scope="col">Started</th>
            <th className={headerCls} scope="col">Duration</th>
            <th className={headerCls} scope="col">Tools</th>
            <th className={headerCls} scope="col">Cost</th>
            <th className={headerCls} scope="col">Flags</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <SessionRow key={s.id} session={s} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SessionsTableEmpty() {
  return (
    <div className="rounded border border-dashed border-rule bg-surface px-6 py-12 text-center">
      <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">
        No sessions yet
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        Run{" "}
        <code className="rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-ink">receipt init</code>{" "}
        in your terminal.
      </p>
    </div>
  )
}

export function SessionsTableSkeleton() {
  const rows = Array.from({ length: 5 })
  return (
    <div className="overflow-hidden rounded border border-rule bg-surface">
      <table className="min-w-full border-collapse">
        <thead className="border-b border-rule bg-sunken/60">
          <tr>
            <th className={headerCls} scope="col">User</th>
            <th className={headerCls} scope="col">Started</th>
            <th className={headerCls} scope="col">Duration</th>
            <th className={headerCls} scope="col">Tools</th>
            <th className={headerCls} scope="col">Cost</th>
            <th className={headerCls} scope="col">Flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((_, i) => (
            <tr key={i} className="border-b border-rule last:border-b-0">
              {Array.from({ length: 6 }).map((__, j) => (
                <td key={j} className="px-3 py-3">
                  <div className="h-3 w-full max-w-[10rem] animate-pulse rounded-sm bg-sunken" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
