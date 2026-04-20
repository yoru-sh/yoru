import { createContext, memo, useContext, useMemo, useState, type ReactNode } from "react"
import type { SessionEvent } from "../../types/receipt"
import { TimelineEvent, formatDurationMs } from "./TimelineEvent"

// Compound-component context per vercel-composition-patterns. Children read it
// via useTimelineGroup(); root owns the toggle state. Default closed.
interface TimelineGroupContextValue {
  expanded: boolean
  toggle: () => void
  count: number
  tool: string
  totalDurationMs: number
  events: SessionEvent[]
  groupKey: string
}

const TimelineGroupContext = createContext<TimelineGroupContextValue | null>(null)

function useTimelineGroup(): TimelineGroupContextValue {
  const ctx = useContext(TimelineGroupContext)
  if (!ctx) {
    throw new Error(
      "TimelineGroup.Summary / TimelineGroup.Details must be rendered inside <TimelineGroup>",
    )
  }
  return ctx
}

interface TimelineGroupProps {
  groupKey: string
  tool: string
  events: SessionEvent[]
  /** Always exactly <TimelineGroup.Summary /> + <TimelineGroup.Details />. */
  children: ReactNode
}

function TimelineGroupRoot({ groupKey, tool, events, children }: TimelineGroupProps) {
  const [expanded, setExpanded] = useState(false)
  const value = useMemo<TimelineGroupContextValue>(() => {
    const totalDurationMs = events.reduce((acc, e) => acc + (e.duration_ms ?? 0), 0)
    return {
      expanded,
      toggle: () => setExpanded((v) => !v),
      count: events.length,
      tool,
      totalDurationMs,
      events,
      groupKey,
    }
  }, [expanded, events, tool, groupKey])
  return <TimelineGroupContext.Provider value={value}>{children}</TimelineGroupContext.Provider>
}

// ── Summary ─────────────────────────────────────────────────────────────────
// Single collapsed row:
//   ▶ Bash  ×N commands (preview, …)   total X.Ys   [expand]
// Click anywhere on the row toggles. Chevron rotates on expand.

function SummaryImpl() {
  const { expanded, toggle, count, tool, totalDurationMs, events, groupKey } =
    useTimelineGroup()
  const previews = useMemo(() => firstNPreviews(events, 2), [events])
  const totalLabel = formatDurationMs(totalDurationMs)
  return (
    <li
      id={`group-${groupKey}`}
      className="motion-safe:animate-feed-in list-none border-b border-dashed border-rule last:border-b-0"
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-controls={`group-details-${groupKey}`}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            toggle()
          }
        }}
        className={
          "group flex items-center gap-2 min-h-8 py-1 cursor-pointer " +
          "hover:bg-sunken/40 focus-within:bg-sunken/40 " +
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper rounded-sm"
        }
      >
        <span
          aria-hidden="true"
          data-expanded={expanded}
          className="w-4 shrink-0 font-mono text-ink text-center transition-transform duration-micro data-[expanded=true]:rotate-90"
        >
          ▶
        </span>
        <span className="w-14 shrink-0 font-sans text-caption uppercase tracking-wider text-ink-muted truncate">
          {tool}
        </span>
        <span className="inline-flex items-center rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-micro text-ink-muted shrink-0">
          ×{count} {pluralize(count, tool)}
        </span>
        <span
          className="flex-1 min-w-0 font-mono text-caption text-ink-muted truncate"
          title={previews.join(", ")}
        >
          {previews.length > 0 ? `(${previews.join(", ")} …)` : ""}
        </span>
        {totalLabel && (
          <span className="shrink-0 font-mono text-caption text-ink-faint tabular-nums whitespace-nowrap">
            total {totalLabel}
          </span>
        )}
        <span
          aria-hidden="true"
          className="shrink-0 font-mono text-micro text-ink-faint group-hover:text-ink"
        >
          [{expanded ? "collapse" : "expand"}]
        </span>
      </div>
    </li>
  )
}

const Summary = memo(SummaryImpl)

// ── Details ─────────────────────────────────────────────────────────────────
// Renders nothing when collapsed (mounted-only-when-expanded — saves a render
// pass for the 25-Bash collapsed-by-default case). When expanded, fans out the
// underlying events as nested TimelineEvent rows.

function DetailsImpl() {
  const { expanded, events, groupKey } = useTimelineGroup()
  if (!expanded) return null
  return (
    <li id={`group-details-${groupKey}`} className="list-none">
      <ol className="ml-4">
        {events.map((event) => (
          <TimelineEvent key={event.id} event={event} nested />
        ))}
      </ol>
    </li>
  )
}

const Details = memo(DetailsImpl)

// Compound binding — `<TimelineGroup.Summary />` / `<TimelineGroup.Details />`.
// Root export is a memoized wrapper so consumers see one symbol.
export const TimelineGroup = Object.assign(memo(TimelineGroupRoot), {
  Summary,
  Details,
})

// ── Helpers ─────────────────────────────────────────────────────────────────

function firstNPreviews(events: SessionEvent[], n: number): string[] {
  const out: string[] = []
  for (const e of events) {
    if (out.length >= n) break
    const s = onelineForPreview(e)
    if (s) out.push(s)
  }
  return out
}

function onelineForPreview(event: SessionEvent): string {
  if (event.content) return truncate(collapseWhitespace(event.content), 40)
  if (event.path) return truncate(event.path, 40)
  if (typeof event.tool_input === "string") return truncate(collapseWhitespace(event.tool_input), 40)
  if (event.tool_input && typeof event.tool_input === "object") {
    const obj = event.tool_input as Record<string, unknown>
    for (const k of ["command", "pattern", "file_path", "path", "query"]) {
      const v = obj[k]
      if (typeof v === "string" && v.length > 0) return truncate(collapseWhitespace(v), 40)
    }
  }
  return ""
}

function collapseWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim()
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s
}

function pluralize(n: number, tool: string): string {
  // Bash → "commands", Read/Edit/Grep → "calls". Conservative; not localized.
  if (tool.toLowerCase() === "bash") return n === 1 ? "command" : "commands"
  return n === 1 ? "call" : "calls"
}
