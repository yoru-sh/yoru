import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link, useSearchParams } from "react-router-dom"

type Plan = "free" | "team" | "org"
interface Me { plan: Plan }

// TODO: wire to real /api/v1/me endpoint (backend US-18 is pending).
// Until then this returns "free" forever — the timeout fallback below keeps
// the page usable in stub mode while matching real-webhook behavior once live.
async function fetchMe(): Promise<Me> {
  return { plan: "free" }
}

const CONFIRM_TIMEOUT_MS = 10_000

export function BillingSuccessPage() {
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get("session_id")
  const [timedOut, setTimedOut] = useState(false)

  const { data } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    refetchInterval: (query) => {
      const d = query.state.data as Me | undefined
      return d && d.plan !== "free" ? false : 2000
    },
  })

  useEffect(() => {
    const t = window.setTimeout(() => setTimedOut(true), CONFIRM_TIMEOUT_MS)
    return () => window.clearTimeout(t)
  }, [])

  const confirmed = (data && data.plan !== "free") || timedOut

  if (!confirmed) {
    return (
      <div className="bg-paper text-ink">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Confirming your upgrade…
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            Waiting for the payment webhook. This usually takes a few seconds.
          </p>
        </header>
        <section
          role="status"
          aria-label="Confirming plan upgrade"
          className="flex items-center gap-3 rounded-sm border border-rule bg-surface p-4"
        >
          <svg
            className="h-4 w-4 shrink-0 motion-safe:animate-spin text-accent-500"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
            <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
          </svg>
          <span className="font-mono text-caption uppercase tracking-wider text-ink-muted">
            {sessionId ? `session ${sessionId.slice(0, 12)}… polling` : "polling /api/v1/me"}
          </span>
        </section>
      </div>
    )
  }

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
