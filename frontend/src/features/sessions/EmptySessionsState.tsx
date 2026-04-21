export interface EmptySessionsStateProps {
  installCommand?: string
}

export function EmptySessionsState({
  installCommand = "receipt init",
}: EmptySessionsStateProps) {
  return (
    <section
      role="status"
      aria-label="No sessions yet"
      className="flex min-h-[calc(100vh-6rem)] flex-col items-center justify-center"
    >
      <div className="mx-auto max-w-sm py-12 text-center">
        <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">
          NO RECEIPTS YET
        </p>
        <p className="mt-3 text-sm text-ink-muted">
          Run{" "}
          <code className="font-mono text-ink">{installCommand}</code>{" "}
          in your terminal — your first agent session shows up here within seconds.
        </p>
        <div className="mt-6 flex flex-col items-center gap-3">
          <a
            href="/docs/install"
            className="inline-flex items-center rounded-sm bg-accent-500 px-4 py-2 font-mono text-caption uppercase tracking-wider text-paper hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          >
            Install in 60s →
          </a>
          <a
            href="/"
            className="rounded-sm font-mono text-caption text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          >
            Skip to dashboard
          </a>
        </div>
      </div>
    </section>
  )
}
