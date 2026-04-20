import { useEffect, useRef } from "react"
import { RedFlagBadge } from "./RedFlagBadge"
import type { RedFlagKind } from "../../types/receipt"

interface LegendRow {
  kind: RedFlagKind
  meaning: string
  example: string
}

const ROWS: LegendRow[] = [
  {
    kind: "secret-pattern",
    meaning: "API key / token regex hit in a tool call or file edit",
    example: "sk_live_… in .env",
  },
  {
    kind: "shell-rm",
    meaning: "rm or rm -rf invocation",
    example: "rm -rf node_modules",
  },
  {
    kind: "migration-edit",
    meaning: "file change under migrations/ or alembic/",
    example: "migrations/005_drop_users.py",
  },
  {
    kind: "env-mutation",
    meaning: "write to .env* files",
    example: "overwrite .env.production",
  },
  {
    kind: "ci-config-edit",
    meaning: "file change in .github/workflows/, .gitlab-ci.yml, etc.",
    example: ".github/workflows/deploy.yml",
  },
]

interface RedFlagLegendProps {
  open: boolean
  onClose: () => void
}

export function RedFlagLegend({ open, onClose }: RedFlagLegendProps) {
  const closeBtnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    closeBtnRef.current?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="red-flag-legend-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-feed-in"
      />
      <div
        role="document"
        className="relative z-10 w-full max-w-2xl overflow-hidden rounded border border-rule bg-surface shadow-2xl animate-feed-in"
      >
        <header className="flex items-center justify-between border-b border-rule px-5 py-3">
          <h2
            id="red-flag-legend-title"
            className="font-mono text-caption uppercase tracking-wider text-ink-muted"
          >
            Red flags — v0
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label="Close legend"
            className="rounded-sm px-2 font-mono text-caption text-ink-muted hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            ✕
          </button>
        </header>
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full border-collapse">
            <thead className="border-b border-rule bg-sunken/60">
              <tr>
                <th className="px-4 py-2 text-left font-mono text-micro uppercase tracking-wider text-ink-faint">
                  Kind
                </th>
                <th className="px-4 py-2 text-left font-mono text-micro uppercase tracking-wider text-ink-faint">
                  Meaning
                </th>
                <th className="px-4 py-2 text-left font-mono text-micro uppercase tracking-wider text-ink-faint">
                  Example
                </th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.kind} className="border-b border-rule last:border-b-0 align-top">
                  <td className="px-4 py-3">
                    <RedFlagBadge kind={row.kind} />
                  </td>
                  <td className="px-4 py-3 font-mono text-caption text-ink">
                    {row.meaning}
                  </td>
                  <td className="px-4 py-3 font-mono text-caption text-ink-muted">
                    <code className="rounded-sm bg-sunken px-1.5 py-0.5">{row.example}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
