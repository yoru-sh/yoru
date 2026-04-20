import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

const RETURN_DELAY_MS = 500

export function BillingCancelPage() {
  const [booting, setBooting] = useState(true)

  useEffect(() => {
    const t = window.setTimeout(() => setBooting(false), RETURN_DELAY_MS)
    return () => window.clearTimeout(t)
  }, [])

  if (booting) {
    return (
      <div className="bg-paper text-ink">
        <section
          role="status"
          aria-label="Returning from checkout"
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
            Returning…
          </span>
        </section>
      </div>
    )
  }

  return (
    <div className="bg-paper text-ink">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          Checkout cancelled — no charge.
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          You can upgrade any time from Settings → Billing.
        </p>
      </header>

      <section
        aria-labelledby="cancel-detail-heading"
        className="rounded-sm border border-rule bg-surface p-4"
      >
        <h2
          id="cancel-detail-heading"
          className="font-mono text-caption uppercase tracking-wider text-ink-muted"
        >
          Still want to upgrade?
        </h2>
        <p className="mt-3 text-sm text-ink-muted">
          Try again whenever you&apos;re ready — your existing receipts and quota
          are unchanged.
        </p>
        <div className="mt-5">
          <Link
            to="/settings/billing"
            className="inline-flex items-center gap-1.5 rounded-sm bg-accent-500 px-4 py-2 text-sm font-semibold text-primary-950 hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          >
            Try again
          </Link>
        </div>
      </section>
    </div>
  )
}
