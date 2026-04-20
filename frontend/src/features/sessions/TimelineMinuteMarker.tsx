import { memo } from "react"

interface TimelineMinuteMarkerProps {
  /** ISO timestamp; rendered as HH:MM (UTC). */
  ts: string
}

function formatHHMM(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mm = String(d.getUTCMinutes()).padStart(2, "0")
  return `${hh}:${mm}`
}

function TimelineMinuteMarkerImpl({ ts }: TimelineMinuteMarkerProps) {
  const label = formatHHMM(ts)
  return (
    <li
      role="separator"
      aria-label={label}
      className="my-3 flex items-center gap-2 font-mono text-caption uppercase tracking-wider text-ink-faint before:content-[''] before:flex-1 before:border-t before:border-rule after:content-[''] after:flex-1 after:border-t after:border-rule list-none"
    >
      <span className="tabular-nums">{label}</span>
    </li>
  )
}

export const TimelineMinuteMarker = memo(TimelineMinuteMarkerImpl)
