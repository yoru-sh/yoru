import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { postCheckoutSession, type Plan } from "../lib/api"
import { toast } from "../components/Toaster"

interface Me {
  plan: Plan
}

// TODO: wire to real /api/v1/me endpoint (backend US-18 is pending).
// Until then, stub returns { plan: "free" } so the Upgrade CTA slice is demoable.
async function fetchMe(): Promise<Me> {
  return { plan: "free" }
}

const PLAN_LABELS: Record<Plan, string> = {
  free: "Free",
  team: "Team",
  org: "Org",
}

const PLAN_SUMMARIES: Record<Plan, string> = {
  free: "Solo account · 5,000 events/month · 7-day retention.",
  team: "Up to 20 seats · 100,000 events/seat/month · 365-day retention.",
  org: "Unlimited seats · unlimited events (rate-limited) · SSO & SCIM.",
}

export function BillingPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [banner, setBanner] = useState(() => searchParams.get("upgraded") === "1")
  const [upgrading, setUpgrading] = useState(false)

  const { data, isLoading, isError } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    refetchInterval: banner ? 3000 : false,
  })

  if (banner && data && data.plan !== "free") {
    setBanner(false)
  }

  async function onUpgradeClick() {
    if (upgrading) return
    setUpgrading(true)
    try {
      const res = await postCheckoutSession("team")
      window.location.href = res.checkout_url
    } catch (err) {
      setUpgrading(false)
      const detail = err instanceof Error ? err.message : String(err)
      toast.error("Couldn't start upgrade", detail)
    }
  }

  function dismissBanner() {
    setBanner(false)
    const next = new URLSearchParams(searchParams)
    next.delete("upgraded")
    next.delete("mock")
    setSearchParams(next, { replace: true })
  }

  const plan = data?.plan ?? "free"
  const showUpgradeCta = !isLoading && !isError && plan === "free"

  return (
    // TODO: nest inside /settings tabs shell once US-21 lands.
    <div className="bg-paper text-ink">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Billing</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Manage your Receipt plan and billing details.
        </p>
      </header>

      {banner && (
        <div
          role="status"
          className="mb-6 flex items-start justify-between gap-4 rounded-sm border border-rule border-l-2 border-l-accent-500 bg-surface px-3 py-2 text-sm text-ink"
        >
          <div>
            <span className="mr-2 font-mono uppercase text-caption text-ink-muted">OK  </span>
            Thanks! Your plan refreshes within 10 seconds.
          </div>
          <button
            type="button"
            onClick={dismissBanner}
            aria-label="Dismiss"
            className="-m-2 p-2 text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            ×
          </button>
        </div>
      )}

      <section
        aria-labelledby="current-plan-heading"
        className="rounded-sm border border-rule bg-surface p-4"
      >
        <h2
          id="current-plan-heading"
          className="font-mono text-caption uppercase tracking-wider text-ink-muted"
        >
          Current plan
        </h2>

        {isLoading ? (
          <div role="status" aria-label="Loading plan" className="mt-3 space-y-2">
            <div className="h-6 w-32 rounded-sm bg-sunken motion-safe:animate-pulse" />
            <div className="h-4 w-2/3 rounded-sm bg-sunken motion-safe:animate-pulse" />
          </div>
        ) : isError ? (
          <p role="alert" className="mt-3 text-sm text-ink">
            <span className="mr-2 font-mono text-ink-muted">[err]</span>
            Couldn&apos;t load your plan. Refresh to retry.
          </p>
        ) : (
          <div className="mt-3">
            <p className="text-lg font-semibold text-ink">{PLAN_LABELS[plan]}</p>
            <p className="mt-1 text-sm text-ink-muted">{PLAN_SUMMARIES[plan]}</p>
          </div>
        )}

        {showUpgradeCta && (
          <div className="mt-5">
            <button
              type="button"
              onClick={() => { void onUpgradeClick() }}
              disabled={upgrading}
              className="inline-flex items-center gap-1.5 rounded-sm bg-accent-500 px-4 py-2 text-sm font-semibold text-primary-950 hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-60"
            >
              {upgrading && (
                <svg
                  className="h-3 w-3 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
                  <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
                </svg>
              )}
              {upgrading ? "Starting checkout…" : "Upgrade to Team — $19/month"}
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
