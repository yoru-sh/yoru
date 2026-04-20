import { useEffect, useRef, useState, type FormEvent } from "react"
import { Navigate, useLocation, useSearchParams } from "react-router-dom"
import { supabase } from "../lib/supabase"
import { useSession } from "../auth/useSession"

const RESEND_COOLDOWN_SECONDS = 60

const INPUT_CLASS =
  "mt-1 w-full rounded border border-rule bg-paper px-3 py-2 text-sm text-ink outline-none " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"

const LABEL_CLASS = "font-mono text-micro uppercase tracking-wider text-ink-faint"

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
  const [password, setPassword] = useState("")
  const [mode, setMode] = useState<"magic" | "password">("magic")
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

  async function signInPassword() {
    setErr(null)
    setSubmitting(true)
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setSubmitting(false)
    if (error) {
      setErr(friendlyError(error))
      return
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (mode === "password") await signInPassword()
    else await sendLink()
  }

  async function onResend() {
    if (cooldown > 0 || submitting) return
    await sendLink()
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm rounded border border-rule bg-surface p-6 shadow-sm">
        <h1 className="font-mono text-2xl font-semibold tracking-tight text-ink">receipt</h1>
        <p className="mt-2 font-mono text-micro uppercase tracking-wider text-ink-faint">
          Audit receipts · AI coding sessions
        </p>

        {tokenExpired && !sent && (
          <div
            role="status"
            className="mt-5 border-l-2 border-accent-500 bg-sunken px-3 py-2 text-sm text-ink"
          >
            <span className="font-mono text-micro uppercase tracking-wider text-ink-muted">
              Session expired
            </span>
            <p className="mt-0.5">Sign in again to continue.</p>
          </div>
        )}

        {sent ? (
          <div className="mt-6 space-y-3" role="status" aria-label="Magic link sent">
            <p className="font-mono text-micro uppercase tracking-wider text-ink-faint">
              Link sent
            </p>
            <p className="text-sm text-ink">
              Check <span className="font-mono text-ink">{email}</span> for a sign-in link.
            </p>
            <button
              type="button"
              onClick={() => { void onResend() }}
              disabled={cooldown > 0 || submitting}
              className="w-full rounded border border-rule px-3 py-2 text-sm text-ink-muted hover:bg-sunken hover:text-ink outline-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-50"
            >
              {submitting
                ? "Resending…"
                : cooldown > 0
                  ? `Resend in ${cooldown}s`
                  : "Resend link"}
            </button>
            {err && (
              <div
                role="alert"
                className="border-l-2 border-flag-env bg-flag-env/5 px-3 py-2 text-sm text-ink"
              >
                <span className="font-mono text-ink-muted">[ERR]</span> {err}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-3">
            <label className="block">
              <span className={LABEL_CLASS}>Email</span>
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={INPUT_CLASS}
                placeholder="you@company.dev"
              />
            </label>
            {mode === "password" && (
              <label className="block">
                <span className={LABEL_CLASS}>Password</span>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={INPUT_CLASS}
                  placeholder="••••••••"
                />
              </label>
            )}
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded bg-accent-500 px-3 py-2 text-sm font-medium text-primary-950 hover:bg-accent-400 outline-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-50"
            >
              {submitting ? "Signing in…" : mode === "password" ? "Sign in" : "Send magic link"}
            </button>
            {err && (
              <div
                role="alert"
                className="border-l-2 border-flag-env bg-flag-env/5 px-3 py-2 text-sm text-ink"
              >
                <span className="font-mono text-ink-muted">[ERR]</span> {err}
              </div>
            )}
            {import.meta.env.DEV && (
              <div className="pt-2 text-center">
                <button
                  type="button"
                  onClick={() => setMode(mode === "password" ? "magic" : "password")}
                  className="rounded-sm text-caption text-ink-muted underline underline-offset-2 outline-none hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
                >
                  {mode === "password" ? "Use magic link instead" : "Dev sign-in (password)"}
                </button>
              </div>
            )}
          </form>
        )}
      </div>
    </div>
  )
}
