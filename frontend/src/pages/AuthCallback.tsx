import { useEffect, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useSession } from "../auth/useSession"

const SESSION_DETECT_TIMEOUT_MS = 3000

export function AuthCallback() {
  const navigate = useNavigate()
  const { session, loading } = useSession()
  const [params] = useSearchParams()
  const [timedOut, setTimedOut] = useState(false)

  const next = params.get("next") || "/"

  useEffect(() => {
    if (!loading && session) {
      navigate(next, { replace: true })
    }
  }, [loading, session, navigate, next])

  useEffect(() => {
    if (session) return
    const id = window.setTimeout(() => {
      if (!session) setTimedOut(true)
    }, SESSION_DETECT_TIMEOUT_MS)
    return () => window.clearTimeout(id)
  }, [session])

  if (timedOut && !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-4">
        <div className="w-full max-w-sm space-y-3 rounded-lg border border-rule bg-surface p-6 text-center shadow-sm">
          <p className="text-sm text-ink">Link expired or already used.</p>
          <Link
            to="/signin"
            className="inline-block rounded border border-rule px-3 py-2 text-caption text-ink-muted hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper text-ink-muted">
      <span>Signing you in…</span>
    </div>
  )
}
