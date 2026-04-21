import { useState } from "react"
import { Link, Outlet, useNavigate } from "react-router-dom"
import { useSession } from "../auth/useSession"
import { UpgradeBanner } from "../features/billing/UpgradeBanner"

export function AppShell() {
  const { session, signOut } = useSession()
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)

  async function onSignOut() {
    if (signingOut) return
    setSigningOut(true)
    try {
      await signOut()
      navigate("/signin", { replace: true })
    } finally {
      setSigningOut(false)
    }
  }

  return (
    <div className="min-h-screen bg-paper text-ink">
      <a
        href="#main"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-3 focus-visible:top-3 focus-visible:z-50 focus-visible:rounded-sm focus-visible:border focus-visible:border-rule focus-visible:bg-surface focus-visible:px-3 focus-visible:py-2 focus-visible:font-mono focus-visible:text-caption focus-visible:text-ink focus-visible:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
      >
        Skip to content
      </a>
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <Link
            to="/"
            className="rounded-sm font-mono text-sm font-semibold tracking-tight text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
          >
            receipt
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-caption text-ink-muted">{session?.user.email}</span>
            <button
              type="button"
              onClick={() => { void onSignOut() }}
              disabled={signingOut}
              className="inline-flex items-center gap-1.5 rounded border border-rule px-2 py-1 text-caption text-ink-muted hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 disabled:opacity-60"
            >
              {signingOut && (
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
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-6 py-6">
        <UpgradeBanner />
        <Outlet />
      </main>
    </div>
  )
}
