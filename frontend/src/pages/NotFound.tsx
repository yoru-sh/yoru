import { Link } from "react-router-dom"

export function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2 bg-paper text-ink-muted">
      <h1 className="font-mono text-xl text-ink">404</h1>
      <Link to="/" className="text-accent-500 underline">Back to sessions</Link>
    </div>
  )
}
