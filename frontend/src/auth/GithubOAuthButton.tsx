// `VITE_API_URL` already includes `/api/v1` (see frontend/.env.local), so we
// just append the relative auth path — same convention as lib/auth-api.ts.
const API_BASE = (import.meta.env.VITE_API_URL as string) || "http://localhost:8000/api/v1"

interface GithubOAuthButtonProps {
  label?: string
}

/**
 * Server-driven OAuth: the button is just a link to the backend, which owns
 * the full Supabase handshake. Frontend stays cookie-only — no Supabase JS,
 * no client-side token juggling.
 *
 *   [this link] → GET /api/v1/auth/github/start
 *   → 302 to GitHub via Supabase
 *   → 302 back to /api/v1/auth/github/callback
 *   → backend mints cookies, 302s to /welcome
 */
export function GithubOAuthButton({ label = "Continue with GitHub" }: GithubOAuthButtonProps) {
  return (
    <a
      href={`${API_BASE}/auth/github/start`}
      className="flex w-full items-center justify-center gap-2 rounded border border-rule bg-paper px-3 py-2 text-sm font-medium text-ink hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
        <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.11.79-.25.79-.56v-1.98c-3.2.7-3.88-1.54-3.88-1.54-.52-1.32-1.28-1.67-1.28-1.67-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.97.1-.74.4-1.26.72-1.54-2.56-.29-5.25-1.28-5.25-5.71 0-1.26.45-2.3 1.19-3.11-.12-.3-.52-1.49.11-3.1 0 0 .97-.31 3.17 1.19a11.04 11.04 0 0 1 5.77 0c2.2-1.5 3.17-1.19 3.17-1.19.63 1.61.23 2.8.11 3.1.74.81 1.19 1.85 1.19 3.11 0 4.44-2.7 5.42-5.27 5.7.41.36.78 1.06.78 2.14v3.17c0 .31.21.68.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
      </svg>
      {label}
    </a>
  )
}
