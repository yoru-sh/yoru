import type { ReactNode } from 'react'

export type FlagKind = 'secret' | 'env' | 'shell' | 'migration' | 'ci'

interface BadgeProps {
  kind: FlagKind
  children?: ReactNode
  className?: string
  title?: string
}

// Static class literals (not template strings) so Tailwind's JIT picks them up.
const STYLES: Record<FlagKind, string> = {
  secret:    'bg-flag-secret-bg    text-flag-secret-fg    ring-flag-secret',
  env:       'bg-flag-env-bg       text-flag-env-fg       ring-flag-env',
  shell:     'bg-flag-shell-bg     text-flag-shell-fg     ring-flag-shell',
  migration: 'bg-flag-migration-bg text-flag-migration-fg ring-flag-migration',
  ci:        'bg-flag-ci-bg        text-flag-ci-fg        ring-flag-ci',
}

const DEFAULT_LABEL: Record<FlagKind, string> = {
  secret:    'secret',
  env:       'env',
  shell:     'rm',
  migration: 'migration',
  ci:        'ci',
}

const ARIA_LABEL: Record<FlagKind, string> = {
  secret:    'red flag: secret pattern detected',
  env:       'red flag: env file mutated',
  shell:     'red flag: shell rm command',
  migration: 'red flag: database migration edited',
  ci:        'red flag: CI config edited',
}

export function Badge({ kind, children, className = '', title }: BadgeProps) {
  return (
    <span
      role="status"
      aria-label={ARIA_LABEL[kind]}
      title={title ?? ARIA_LABEL[kind]}
      className={
        'inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 ' +
        'font-mono text-micro font-semibold uppercase tracking-wider ' +
        'ring-1 ring-inset whitespace-nowrap ' +
        STYLES[kind] + ' ' + className
      }
    >
      <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-75" />
      {children ?? DEFAULT_LABEL[kind]}
    </span>
  )
}
