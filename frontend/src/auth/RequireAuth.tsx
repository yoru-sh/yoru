import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { useSession } from "./useSession"

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-ink-muted">
        <span>Loading…</span>
      </div>
    )
  }

  if (!session) {
    return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />
  }

  return <>{children}</>
}
