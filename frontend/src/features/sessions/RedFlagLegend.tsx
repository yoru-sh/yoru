import { RedFlagBadge } from "./RedFlagBadge"
import { Modal } from "../../components/ui/Modal"
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
    kind: "shell-destructive",
    meaning: "rm / rm -rf, curl|sh remote-code-exec, or git push --force / reset --hard",
    example: "curl … | sh — git push --force — rm -rf node_modules",
  },
  {
    kind: "db-destructive",
    meaning: "DROP/TRUNCATE/DELETE-without-WHERE/UPDATE-without-WHERE on a database",
    example: "DELETE FROM sessions",
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
  return (
    <Modal open={open} onClose={onClose} title="Red flags — v0" size="2xl">
      <header className="flex items-center justify-between border-b border-rule px-5 py-3">
        <h2 className="font-mono text-caption uppercase tracking-wider text-ink-muted">
          Red flags — v0
        </h2>
        <button
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
    </Modal>
  )
}
