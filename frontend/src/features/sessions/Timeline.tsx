import { useState } from "react"
import type { SessionEvent } from "../../types/receipt"
import { TimelineEvent } from "./TimelineEvent"

interface TimelineProps {
  events: SessionEvent[]
  onFlagClick: () => void
}

export function Timeline({ events, onFlagClick }: TimelineProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (events.length === 0) {
    return (
      <section
        aria-label="Timeline"
        className="rounded border border-dashed border-rule bg-surface px-6 py-10 text-center"
      >
        <p className="font-mono text-caption text-ink-muted">
          No events captured for this session.
        </p>
      </section>
    )
  }

  return (
    <section aria-label="Timeline" className="rounded border border-rule bg-surface p-4">
      <h2 className="mb-4 font-mono text-micro uppercase tracking-wider text-ink-faint">
        Timeline · {events.length} event{events.length === 1 ? "" : "s"}
      </h2>
      <ol className="relative space-y-4 before:absolute before:left-3 before:top-1 before:bottom-1 before:w-px before:bg-rule">
        {events.map((event) => (
          <TimelineEvent
            key={event.id}
            event={event}
            expanded={expanded.has(event.id)}
            onToggle={() => toggle(event.id)}
            onFlagClick={onFlagClick}
          />
        ))}
      </ol>
    </section>
  )
}
