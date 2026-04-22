import type { Plan } from "../lib/api"

interface ProTierBannerProps {
  plan: Plan
}

const PAID_LABELS: Record<Exclude<Plan, "free">, string> = {
  pro: "Pro",
  team: "Team",
  org: "Org",
}

export function ProTierBanner({ plan }: ProTierBannerProps) {
  if (plan === "free") return null

  const label = PAID_LABELS[plan]

  return (
    <div
      role="status"
      aria-label="Plan status"
      className="rounded-sm border border-rule border-l-2 border-l-accent-500 bg-surface px-3 py-2 font-sans text-sm text-ink"
    >
      <span className="mr-2 font-mono uppercase text-caption text-ink-muted">OK  </span>
      You&apos;re on {label} — unlimited sessions, retention unlocked
    </div>
  )
}
