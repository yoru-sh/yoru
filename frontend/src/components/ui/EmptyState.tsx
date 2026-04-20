import type { ReactNode } from "react"

export interface EmptyStateProps {
  heading: string
  body: string
  action?: ReactNode
}

export function EmptyState({ heading, body, action }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="mx-auto max-w-sm py-12 text-center"
    >
      <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">
        {heading}
      </p>
      <p className="mt-2 text-sm text-ink-muted">{body}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
