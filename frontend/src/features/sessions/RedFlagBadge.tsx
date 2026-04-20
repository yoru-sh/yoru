import { memo } from "react"
import { Badge, type FlagKind } from "../../components/Badge"
import type { RedFlagKind } from "../../types/receipt"

// Static literal maps so Tailwind JIT resolves every utility referenced via
// Badge's per-kind class bundle. No template-string composition — self-learning
// §static-class-literal-maps.
const KIND_MAP: Record<RedFlagKind, FlagKind> = {
  "secret-pattern": "secret",
  "env-mutation":   "env",
  "shell-rm":       "shell",
  "migration-edit": "migration",
  "ci-config-edit": "ci",
}

const LABEL: Record<RedFlagKind, string> = {
  "secret-pattern": "secret",
  "env-mutation":   "env",
  "shell-rm":       "rm",
  "migration-edit": "migration",
  "ci-config-edit": "ci",
}

interface RedFlagBadgeProps {
  kind: RedFlagKind
  className?: string
  onClick?: () => void
}

function RedFlagBadgeImpl({ kind, className, onClick }: RedFlagBadgeProps) {
  const badge = (
    <Badge kind={KIND_MAP[kind]} className={className} title={kind}>
      {LABEL[kind]}
    </Badge>
  )
  if (!onClick) return badge
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Open red-flag legend for ${kind}`}
      className={
        "inline-flex cursor-pointer rounded-sm " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
        "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
      }
    >
      {badge}
    </button>
  )
}

export const RedFlagBadge = memo(RedFlagBadgeImpl)
