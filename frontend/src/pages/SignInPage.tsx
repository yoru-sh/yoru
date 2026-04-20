import { useEffect, useRef, useState, type FormEvent } from "react"
import { Navigate, useLocation, useSearchParams } from "react-router-dom"
import { supabase } from "../lib/supabase"
import { useSession } from "../auth/useSession"

const RESEND_COOLDOWN_SECONDS = 60

function buildRedirectTo(next: string | null): string {
  const base = `${window.location.origin}/auth/callback`
  if (!next || next === "/") return base
  return `${base}?next=${encodeURIComponent(next)}`
}

function friendlyError(err: { status?: number; message?: string }): string {
  if (err.status === 429 || /rate.?limit|too many/i.test(err.message ?? "")) {
    return "Too many requests. Wait a minute, then try again."
  }
  return err.message ?? "Something went wrong. Please try again."
}

export function SignInPage() {
  const { session, loading } = useSession()
  const location = useLocation() as { state?: { from?: string } }
  const from = location.state?.from ?? null
  const [searchParams] = useSearchParams()
  const tokenExpired = searchParams.get("reason") === "token-expired"

  const [email, setEmail] = useState("")
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (cooldown <= 0) return
    timerRef.current = window.setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
  }, [cooldown])

  if (loading) return null
  if (session) return <Navigate to={from ?? "/"} replace />

  async function sendLink() {
    setErr(null)
    setSubmitting(true)
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: buildRedirectTo(from) },
    })
    setSubmitting(false)
    if (error) {
      setErr(friendlyError(error))
      return
    }
    setSent(true)
    setCooldown(RESEND_COOLDOWN_SECONDS)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    await sendLink()
  }

  async function onResend() {
    if (cooldown > 0 || submitting) return
    await sendLink()
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm rounded-lg border border-rule bg-surface p-6 shadow-sm">
        <h1 className="font-mono text-lg font-semibold text-ink">receipt</h1>
        <p className="mt-1 text-caption text-ink-muted">Audit receipts for your AI coding sessions.</p>

        {tokenExpired && !sent && (
          <div
            role="status"
            className="mt-4 rounded border border-rule bg-sunken px-3 py-2 text-caption text-ink"
          >
            Your session expired — sign in again to continue.
          </div>
        )}

        {sent ? (
          <div className="mt-6 space-y-3">
            <p className="text-sm text-ink">
              Check <span className="font-medium">{email}</span> for a sign-in link.
            </p>
            <button
              type="button"
              onClick={() => { void onResend() }}
              disabled={cooldown > 0 || submitting}
              className="w-full rounded border border-rule px-3 py-2 text-sm text-ink-muted hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 disabled:opacity-50"
            >
              {submitting
                ? "Resending…"
                : cooldown > 0
                  ? `Resend in ${cooldown}s`
                  : "Resend link"}
            </button>
            {err && <p className="text-caption text-flag-env">{err}</p>}
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-3">
            <label className="block">
              <span className="text-caption text-ink-muted">Email</span>
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded border border-rule bg-paper px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent-500"
                placeholder="you@company.dev"
              />
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded bg-accent-500 px-3 py-2 text-sm font-medium text-primary-950 hover:bg-accent-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 disabled:opacity-50"
            >
              {submitting ? "Sending…" : "Send magic link"}
            </button>
            {err && <p className="text-caption text-flag-env">{err}</p>}
          </form>
        )}
      </div>
    </div>
  )
}
