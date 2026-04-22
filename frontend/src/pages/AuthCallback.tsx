import { Navigate } from "react-router-dom"

// Legacy route from the Supabase magic-link era. Cookie-based auth lands the
// user directly on /welcome after /auth/signin, so this callback is inert and
// just redirects home. Keep the route registered so old emailed links don't 404.
export function AuthCallback() {
  return <Navigate to="/" replace />
}
