import { useState } from "react"
import { toast } from "../components/Toaster"

const STEPS: { label: string; code: string }[] = [
  { label: "1. Install the CLI", code: "pip install receipt-cli" },
  { label: "2. Initialize — opens browser to mint a hook token", code: "receipt init" },
  {
    label: "3. Run any Claude Code session — your first Receipt appears in seconds",
    code: "claude",
  },
]

function CodeStep({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false)

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(code)
      toast.success("Copied", code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Copy failed", "Select the text and copy manually.")
    }
  }

  return (
    <section className="space-y-2">
      <p className="font-mono text-micro uppercase tracking-wider text-ink-muted">{label}</p>
      <pre className="font-mono bg-sunken rounded-sm p-4 border border-rule relative text-sm text-ink pr-20 whitespace-pre-wrap break-all">
        <code>{code}</code>
        <button
          type="button"
          onClick={() => { void onCopy() }}
          aria-label={`Copy: ${code}`}
          className="absolute right-2 top-2 rounded-sm border border-rule bg-surface px-2 py-1 font-mono text-caption uppercase tracking-wider text-ink-muted hover:border-accent-500 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </pre>
    </section>
  )
}

export function DocsInstallPage() {
  return (
    <main
      id="main"
      className="min-h-screen flex flex-col justify-center max-w-2xl mx-auto px-6"
    >
      <header className="space-y-3">
        <p className="font-mono text-micro uppercase tracking-wider text-ink-muted">
          § Install receipt
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Install Receipt</h1>
        <p className="text-sm text-ink-muted">
          Three commands. About 60 seconds. Your first Receipt appears as soon as you run a Claude
          Code session.
        </p>
      </header>

      <div className="my-6 border-t border-dashed border-rule" aria-hidden="true" />

      <div className="space-y-6">
        {STEPS.map((s) => (
          <CodeStep key={s.code} label={s.label} code={s.code} />
        ))}
      </div>

      <div className="my-6 border-t border-dashed border-rule" aria-hidden="true" />

      <div className="space-y-3">
        <p className="font-mono text-micro uppercase tracking-wider text-ink-muted">Next</p>
        <a
          href="/"
          className="inline-block rounded bg-accent-500 px-4 py-2 text-sm font-medium text-primary-950 hover:bg-accent-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
        >
          See your sessions →
        </a>
      </div>
    </main>
  )
}
