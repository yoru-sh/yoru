import { useState } from "react"
import type { FileChanged, FileOp } from "../../types/receipt"

interface FilesChangedAccordionProps {
  files: FileChanged[]
}

const OP_STYLE: Record<FileOp, string> = {
  create: "bg-emerald-900/30 text-emerald-200 ring-emerald-900/50",
  edit:   "bg-accent-900/30 text-accent-200 ring-accent-900/50",
  delete: "bg-flag-env-bg text-flag-env-fg ring-flag-env",
}

export function FilesChangedAccordion({ files }: FilesChangedAccordionProps) {
  const [open, setOpen] = useState<Set<string>>(() => new Set())

  const toggle = (path: string) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  if (files.length === 0) {
    return (
      <section
        aria-label="Files changed"
        className="rounded border border-dashed border-rule bg-surface px-6 py-8 text-center"
      >
        <p className="font-mono text-caption text-ink-muted">
          No files were changed in this session.
        </p>
      </section>
    )
  }

  return (
    <section
      aria-label="Files changed"
      className="rounded border border-rule bg-surface"
    >
      <header className="border-b border-rule px-4 py-3">
        <h2 className="font-mono text-micro uppercase tracking-wider text-ink-faint">
          Files changed · {files.length}
        </h2>
      </header>
      <ul>
        {files.map((file) => {
          const isOpen = open.has(file.path)
          return (
            <li key={file.path} className="border-b border-rule last:border-b-0">
              <button
                type="button"
                onClick={() => toggle(file.path)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-500"
              >
                <span
                  className={
                    "inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 " +
                    "font-mono text-micro font-semibold uppercase tracking-wider ring-1 ring-inset " +
                    OP_STYLE[file.op]
                  }
                >
                  {file.op}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink">
                  {file.path}
                </span>
                <span className="shrink-0 font-mono text-caption tabular-nums text-emerald-400">
                  +{file.additions}
                </span>
                <span className="shrink-0 font-mono text-caption tabular-nums text-flag-env-fg">
                  −{file.deletions}
                </span>
                <span className="shrink-0 font-mono text-micro text-ink-faint">
                  {isOpen ? "−" : "+"}
                </span>
              </button>
              {isOpen && (
                <div className="border-t border-rule bg-sunken/60 px-4 py-3 font-mono text-micro text-ink-muted">
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
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

