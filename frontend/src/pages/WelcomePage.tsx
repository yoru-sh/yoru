import { useQuery } from "@tanstack/react-query"
import { Navigate } from "react-router-dom"
import { EmptySessionsState } from "../features/sessions/EmptySessionsState"
import { getSessionsCount } from "../lib/api"

export function WelcomePage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["sessions", "welcome-check"],
    queryFn: getSessionsCount,
  })

  if (isPending) {
    return (
      <div
        role="status"
        aria-label="Loading"
        className="flex min-h-[calc(100vh-6rem)] items-center justify-center text-ink-muted"
      >
        <span className="font-mono text-caption uppercase tracking-wider">Loading…</span>
      </div>
    )
  }

  // On error, treat as empty so brand-new users still land on the welcome copy
  // instead of a hard error state — count is best-effort, the install path is the goal.
  if (isError || (data?.total ?? 0) === 0) {
    return <EmptySessionsState />
  }

  return <Navigate to="/" replace />
}
