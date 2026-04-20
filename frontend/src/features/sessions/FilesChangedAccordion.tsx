import type { FileChanged, FileOp } from "../../types/receipt"
import { EmptyState } from "../../components/ui/EmptyState"

interface FilesChangedAccordionProps {
  files: FileChanged[]
}

const OP_CLASS: Record<FileOp, string> = {
  create: "bg-sunken text-ink ring-rule",
  edit:   "bg-accent-500/10 text-accent-500 ring-accent-500/40",
  delete: "bg-flag-env-bg text-flag-env-fg ring-flag-env/60",
}

export function FilesChangedAccordion({ files }: FilesChangedAccordionProps) {
  if (files.length === 0) {
    return (
      <section aria-label="Files changed" className="px-4 py-6">
        <EmptyState
          heading="NO FILES CHANGED"
          body="No files changed in this session."
        />
      </section>
    )
  }

  return (
    <section aria-label="Files changed" className="px-4 py-4">
      <h2 className="mb-2 font-mono text-micro uppercase tracking-wider text-ink-faint">
        § Files changed · {files.length}
      </h2>
      <ul>
        {files.map((file) => (
          <li key={file.path} className="border-b border-dashed border-rule last:border-b-0">
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper rounded-sm">
                <span
                  className={`inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 font-mono text-micro font-semibold uppercase tracking-wider ring-1 ring-inset ${OP_CLASS[file.op]}`}
                >
                  {file.op}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink">
                  {file.path}
                </span>
                <span className="shrink-0 font-mono text-caption tabular-nums text-accent-500">
                  +{file.additions}
                </span>
                <span className="shrink-0 font-mono text-caption tabular-nums text-flag-env-fg">
                  −{file.deletions}
                </span>
                <span
                  aria-hidden="true"
                  className="shrink-0 font-mono text-micro text-ink-faint group-open:rotate-90 motion-safe:transition-transform motion-safe:duration-micro"
                >
                  ›
                </span>
              </summary>
              <div className="mt-1 rounded-sm bg-sunken/60 px-3 py-2 font-mono text-micro text-ink-muted">
                <p>
                  <span className="text-ink-faint">op:</span> {file.op}
                  {"   "}
                  <span className="text-ink-faint">+</span>{file.additions}
                  {"   "}
                  <span className="text-ink-faint">−</span>{file.deletions}
                </p>
                <p className="mt-1 text-ink-faint">
                  Diff view coming in v1 — trail JSON is available at{" "}
                  <code className="text-ink-muted">/sessions/:id/trail</code>.
                </p>
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  )
}
