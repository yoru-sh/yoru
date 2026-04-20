import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useSearchParams } from "react-router-dom"

export function BillingSuccessPage() {
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get("session_id")
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!sessionId) return
    void queryClient.invalidateQueries({ queryKey: ["me"] })
  }, [sessionId, queryClient])

  return (
    <div className="bg-paper text-ink">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          You&apos;re subscribed to Receipt Team — thanks!
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          Your plan refreshes within a few seconds. Receipts captured by your CLI
          will start counting against the new quota immediately.
        </p>
      </header>

      <section
        aria-labelledby="success-detail-heading"
        className="rounded-sm border border-rule bg-surface p-4"
      >
        <h2
          id="success-detail-heading"
          className="font-mono text-caption uppercase tracking-wider text-ink-muted"
        >
          What&apos;s next
        </h2>
        <p className="mt-3 text-sm text-ink-muted">
          Manage seats and billing details from{" "}
          <Link
            to="/settings/billing"
            className="rounded-sm text-ink underline decoration-rule underline-offset-2 hover:decoration-accent-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            Settings → Billing
          </Link>
          .
        </p>
        <div className="mt-5">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 rounded-sm bg-accent-500 px-4 py-2 text-sm font-semibold text-primary-950 hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          >
            Return to dashboard
          </Link>
        </div>
      </section>
    </div>
  )
}
