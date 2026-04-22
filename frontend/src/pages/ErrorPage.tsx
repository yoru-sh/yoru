import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom"

// React Router error boundary. Attached per-route (errorElement) so a thrown
// error inside a loader or a component render shows the Swiss error card
// instead of the default "Hey developer" placeholder.
//
// Visual convention:
//   * All-caps rubric label `§ ERROR · <status>` matching rest of app
//   * Big mono code-style status (404 / 500 / message)
//   * Plain-language body
//   * Dashed rule separator
//   * Two CTAs: "← Sessions" (safe home) + "Reload" (retry once)
// No illustration — Swiss discipline keeps it text + rules only.

export function ErrorPage() {
  const error = useRouteError()

  let status: string | number = "ERR"
  let heading = "Something broke"
  let detail = ""

  if (isRouteErrorResponse(error)) {
    status = error.status
    heading = error.statusText || heading
    detail = typeof error.data === "string" ? error.data : (error.data?.message ?? "")
  } else if (error instanceof Error) {
    status = error.name || "Error"
    heading = error.message || heading
    detail = (import.meta.env.DEV && error.stack) || ""
  }

  return (
    <div className="mx-auto max-w-xl px-6 py-16">
      <p className="font-mono text-micro uppercase tracking-wider text-ink-faint">
        § error · <span className="tabular-nums">{status}</span>
      </p>
      <h1 className="mt-2 font-sans text-2xl font-semibold text-ink">{heading}</h1>

      <hr className="my-4 border-t border-dashed border-rule" />

      {detail && (
        <pre className="mb-4 max-h-64 overflow-auto rounded-sm bg-sunken px-3 py-2 font-mono text-caption leading-relaxed text-ink-muted whitespace-pre-wrap break-words">
          {detail}
        </pre>
      )}

      <p className="font-sans text-sm text-ink-muted leading-relaxed">
        {status === 404
          ? "This page doesn't exist. It may have been moved or the URL is wrong."
          : "An unexpected error occurred. You can try reloading, or return to your sessions."}
      </p>

      <div className="mt-6 flex items-center gap-2">
        <Link
          to="/"
          className={
            "inline-flex items-center gap-1 rounded-sm border border-rule bg-surface px-3 py-1.5 " +
            "font-mono text-caption uppercase tracking-wider text-ink " +
            "hover:bg-sunken " +
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
            "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          }
        >
          ← Sessions
        </Link>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className={
            "inline-flex items-center gap-1 rounded-sm border border-accent-500/50 bg-accent-500/10 px-3 py-1.5 " +
            "font-mono text-caption uppercase tracking-wider text-accent-500 " +
            "hover:bg-accent-500/20 " +
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
            "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          }
        >
          ↻ Reload
        </button>
      </div>
    </div>
  )
}
