import type { FileChanged, FileOp, RedFlagKind, SessionDetail } from "../../types/receipt"
import { RedFlagBadge } from "./RedFlagBadge"

interface FileChangedRailProps {
  session: SessionDetail
}

const OP_CLASS: Record<FileOp, string> = {
  create: "bg-sunken text-ink ring-rule",
  edit:   "bg-accent-500/10 text-accent-500 ring-accent-500/40",
  delete: "bg-flag-env-bg text-flag-env-fg ring-flag-env/60",
}

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

export function FileChangedRail({ session }: FileChangedRailProps) {
  const files = session.files_changed ?? []
  const flagEvents = (session.events ?? []).filter((e) => e.flag)

  return (
    <aside
      aria-label="Session rail"
      className="space-y-4 lg:sticky lg:top-4 lg:self-start"
    >
      <FilesPanel files={files} />
      <FlagsPanel flags={session.flags} flagEvents={flagEvents} />
    </aside>
  )
}

function FilesPanel({ files }: { files: FileChanged[] }) {
  return (
    <section
      aria-label="Files changed"
      className="rounded-sm border border-rule bg-surface"
    >
      <header className="flex items-baseline justify-between border-b border-dashed border-rule px-4 py-2">
        <h2 className={RUBRIC}>Files changed</h2>
        <span className={`${RUBRIC} tabular-nums`}>
          {files.length} file{files.length === 1 ? "" : "s"}
        </span>
      </header>
      {files.length === 0 ? (
        <p className="px-4 py-3 font-sans text-caption text-ink-muted">
          No file changes recorded.
        </p>
      ) : (
        <ul>
          {files.map((file) => (
            <li key={file.path} className="border-b border-dashed border-rule last:border-b-0">
              <a
                href="#"
                className="group flex items-center gap-2 px-4 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper hover:bg-sunken/40"
                title={file.path}
              >
                <span
                  className={`inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 font-mono text-micro font-semibold uppercase tracking-wider ring-1 ring-inset ${OP_CLASS[file.op]}`}
                >
                  {file.op}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink">
                  {file.path}
                </span>
                <span className="shrink-0 font-mono text-micro tabular-nums text-accent-500">
                  +{file.additions}
                </span>
                <span className="shrink-0 font-mono text-micro tabular-nums text-flag-env-fg">
                  −{file.deletions}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

interface FlagsPanelProps {
  flags: RedFlagKind[]
  flagEvents: SessionDetail["events"]
}

function FlagsPanel({ flags, flagEvents }: FlagsPanelProps) {
  if (flags.length === 0 && flagEvents.length === 0) return null

  return (
    <section
      aria-label="Red flags"
      className="rounded-sm border border-rule bg-surface"
    >
      <header className="flex items-baseline justify-between border-b border-dashed border-rule px-4 py-2">
        <h2 className={RUBRIC}>Red flags</h2>
        <span className={`${RUBRIC} tabular-nums`}>
          {flags.length} kind{flags.length === 1 ? "" : "s"}
        </span>
      </header>

      {flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-dashed border-rule px-4 py-2.5">
          {flags.map((kind) => (
            <RedFlagBadge key={kind} kind={kind} />
          ))}
        </div>
      )}

      {flagEvents.length > 0 && (
        <ul>
          {flagEvents.slice(0, 8).map((event) => (
            <li
              key={event.id}
              className="border-b border-dashed border-rule last:border-b-0"
            >
              <a
                href={`#event-${event.id}`}
                className="group flex items-center gap-2 px-4 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper hover:bg-sunken/40"
              >
                {event.flag && <RedFlagBadge kind={event.flag} />}
                <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink-muted">
                  {event.file_path ?? event.tool_name ?? event.text ?? "flagged event"}
                </span>
                <span aria-hidden className="shrink-0 font-mono text-micro text-ink-faint">
                  ↗
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
