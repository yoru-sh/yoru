import { useState, type FormEvent } from "react"
import { Link, Navigate, useLocation } from "react-router-dom"
import { signup, AuthError } from "../lib/auth-api"
import { useSession } from "../auth/useSession"
import { GithubOAuthButton } from "../auth/GithubOAuthButton"

const INPUT_CLASS =
  "mt-1 w-full rounded border border-rule bg-paper px-3 py-2 text-sm text-ink outline-none " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"

const LABEL_CLASS = "font-mono text-micro uppercase tracking-wider text-ink-faint"

function friendlyError(err: unknown): string {
  if (err instanceof AuthError) {
    if (err.status === 409) return "An account with this email already exists — sign in instead."
    if (err.status === 400) return err.detail || "Check the form: something is missing or invalid."
    if (err.status === 429) return "Too many requests. Wait a minute, then try again."
    return err.detail || `Signup failed (${err.status}).`
  }
  return "Something went wrong. Please try again."
}

export function SignUpPage() {
  const { user, loading, refresh } = useSession()
  const location = useLocation() as { state?: { from?: string } }
  const from = location.state?.from ?? null

  const [firstName, setFirstName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [err, setErr] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (loading) return null
  if (user) return <Navigate to={from ?? "/welcome"} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    if (password.length < 8) {
      setErr("Password must be at least 8 characters.")
      return
    }
    setSubmitting(true)
    try {
      await signup({
        email,
        password,
        first_name: firstName || undefined,
      })
      await refresh()
    } catch (error) {
      setErr(friendlyError(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 py-10">
      <div className="w-full max-w-sm rounded border border-rule bg-surface p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <img src="/yoru-mark.png" alt="" aria-hidden="true" className="h-8 w-8" />
          <h1 className="font-mono text-2xl font-semibold tracking-tight text-ink">yoru</h1>
        </div>
        <p className="mt-2 font-mono text-micro uppercase tracking-wider text-ink-faint">
          Create your account
        </p>

        <div className="mt-6">
          <GithubOAuthButton label="Sign up with GitHub" />
        </div>

        <div className="my-5 flex items-center gap-3">
          <span className="h-px flex-1 bg-rule" aria-hidden="true" />
          <span className="font-mono text-micro uppercase tracking-wider text-ink-faint">or</span>
          <span className="h-px flex-1 bg-rule" aria-hidden="true" />
        </div>

        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <label className="block">
            <span className={LABEL_CLASS}>First name (optional)</span>
            <input
              type="text"
              autoComplete="given-name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className={INPUT_CLASS}
              placeholder="Loic"
            />
          </label>
          <label className="block">
            <span className={LABEL_CLASS}>Email</span>
            <input
              type="email"
              required
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT_CLASS}
              placeholder="you@company.dev"
            />
          </label>
          <label className="block">
            <span className={LABEL_CLASS}>Password</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={INPUT_CLASS}
              placeholder="At least 8 characters"
            />
          </label>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded bg-accent-500 px-3 py-2 text-sm font-medium text-primary-950 hover:bg-accent-400 outline-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-50"
          >
            {submitting ? "Creating account…" : "Create account"}
          </button>
          {err && (
            <div
              role="alert"
              className="border-l-2 border-flag-env bg-flag-env/5 px-3 py-2 text-sm text-ink"
            >
              <span className="font-mono text-ink-muted">[ERR]</span> {err}
            </div>
          )}
        </form>

        <hr className="my-5 border-dashed border-rule" />

        <p className="font-sans text-sm text-ink-muted">
          Already have an account?{" "}
          <Link
            to="/signin"
            className="font-medium text-accent-600 hover:text-accent-500 underline-offset-2 hover:underline"
          >
            Sign in →
          </Link>
        </p>
      </div>
    </div>
  )
}
