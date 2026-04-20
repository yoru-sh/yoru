import { Badge, type FlagKind } from './Badge'

interface LegendEntry {
  kind: FlagKind
  label: string
  blurb: string
}

const FLAGS: LegendEntry[] = [
  { kind: 'secret',    label: 'secret-pattern',  blurb: 'API key, token, or credential matched a regex' },
  { kind: 'env',       label: 'env-mutation',    blurb: '.env* file was created or modified' },
  { kind: 'shell',     label: 'shell-rm',        blurb: 'rm / rm -rf invoked in a shell tool call' },
  { kind: 'migration', label: 'migration-edit',  blurb: 'database migration file was touched' },
  { kind: 'ci',        label: 'ci-config-edit',  blurb: 'CI config (.github/, ci.yml, …) was edited' },
]

interface RedFlagLegendProps {
  className?: string
  heading?: string | null
}

export function RedFlagLegend({ className = '', heading = 'Red flags' }: RedFlagLegendProps) {
  return (
    <section className={'text-ink ' + className} aria-label="Red-flag legend">
      {heading !== null && (
        <h2 className="mb-3 font-mono text-caption uppercase tracking-wider text-ink-muted">
          {heading}
        </h2>
      )}
      <dl className="grid gap-2">
        {FLAGS.map(({ kind, label, blurb }) => (
          <div key={kind} className="grid grid-cols-[10rem_1fr] items-center gap-3">
            <dt>
              <Badge kind={kind}>{label}</Badge>
            </dt>
            <dd className="text-caption text-ink-muted">{blurb}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
