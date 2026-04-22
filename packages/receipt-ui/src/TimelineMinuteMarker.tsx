import { memo } from "react"

interface TimelineMinuteMarkerProps {
  /** ISO timestamp; rendered as HH:MM (UTC). */
  ts: string
}

function formatHHMM(ts: string): string {
  // Local HH:MM — consistent with TimelineEvent + TimelineGroup. The Hero
  // still shows the full ISO UTC timestamp for audit reference.
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const hh = String(d.getHours()).padStart(2, "0")
  const mm = String(d.getMinutes()).padStart(2, "0")
  return `${hh}:${mm}`
}

function TimelineMinuteMarkerImpl({ ts }: TimelineMinuteMarkerProps) {
  const label = formatHHMM(ts)
  // Sticky: marker sticks to the top of the scroll container once its row
  // reaches the top edge. Gives the reader a permanent "you are in this
  // minute" cue while scrolling long sessions (200+ events). z-10 keeps it
  // above TimelineEvent rows; bg-paper prevents row text bleeding through.
  return (
    <li
      role="separator"
      aria-label={label}
      // pointer-events-none: the sticky marker sits on top of the first row
      // of its minute bucket and used to swallow clicks on that row (e.g. the
      // TimelineGroup `[tool] Bash ×3` header refused to expand because the
      // marker was catching the click). Visual separator only — not interactive.
      className={
        "sticky top-0 z-10 pointer-events-none -mx-4 bg-paper px-4 py-1 " +
        "flex items-center gap-2 font-mono text-caption uppercase tracking-wider text-ink-faint " +
        "before:content-[''] before:flex-1 before:border-t before:border-rule " +
        "after:content-[''] after:flex-1 after:border-t after:border-rule list-none"
      }
    >
      <span className="tabular-nums">{label}</span>
    </li>
  )
}

export const TimelineMinuteMarker = memo(TimelineMinuteMarkerImpl)
