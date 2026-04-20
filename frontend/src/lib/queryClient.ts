import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query"
import { ApiError } from "./api"
import { pushToast } from "../components/Toaster"

// Body may be FastAPI JSON `{detail: "…"}`, plain text, or a stack.
// Extract one safe line and cap width so stacks/SQL can't leak.
function oneLineDetail(body: string): string {
  const MAX = 120
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    if (typeof parsed.detail === "string") {
      return parsed.detail.split("\n")[0].trim().slice(0, MAX)
    }
  } catch {
    /* not JSON — fall through */
  }
  const first = (body.split("\n")[0] ?? "").trim().slice(0, MAX)
  return first || "Server error"
}

function notifyQueryError(error: unknown): void {
  if (error instanceof ApiError) {
    // 401: apiFetch's signOut latch + RequireAuth redirect handle it.
    // 404: page-level empty / not-found surface handles it.
    if (error.status === 401 || error.status === 404) return
    pushToast({ kind: "error", title: `[${error.status}] ${oneLineDetail(error.body)}` })
    return
  }
  pushToast({ kind: "error", title: "[off] Couldn't reach the server." })
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => notifyQueryError(error),
  }),
  mutationCache: new MutationCache({
    onError: (error) => notifyQueryError(error),
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})
