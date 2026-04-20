import { useMemo } from "react"
import type { SessionEvent } from "../../types/receipt"
import { EmptyState } from "../../components/ui/EmptyState"
import { TimelineEvent } from "./TimelineEvent"
import { TimelineGroup } from "./TimelineGroup"
import { TimelineMinuteMarker } from "./TimelineMinuteMarker"

interface TimelineProps {
  events: SessionEvent[]
  /** Forwarded to flagged TimelineEvent rows so the legend modal can open. */
  onFlagClick?: () => void
}

// Minimum size to coalesce consecutive same-tool events into a group.
// Two same-tool calls read fine as two rows; three+ start to wall-of-sames.
// (SESSION-DETAIL-V1.md §8 open question 1, committed value.)
const MIN_GROUP_SIZE = 3

type TimelineNode =
  | { kind: "marker"; key: string; ts: string }
  | { kind: "event"; key: string; event: SessionEvent }
  | { kind: "group"; key: string; tool: string; groupKey: string; events: SessionEvent[] }

export function Timeline({ events, onFlagClick }: TimelineProps) {
  const nodes = useMemo(() => buildNodes(events), [events])

  if (events.length === 0) {
    return (
      <section aria-label="Timeline" className="px-4 py-6">
        <EmptyState
          heading="SESSION IN PROGRESS"
          body="No events recorded yet. Tool calls and file edits will appear here as they stream."
        />
      </section>
    )
  }

  return (
    <section aria-label="Timeline" className="px-4 py-4">
      <h2 className="mb-2 font-mono text-micro uppercase tracking-wider text-ink-faint">
        § Timeline · {events.length} event{events.length === 1 ? "" : "s"}
      </h2>
      <ol>
        {nodes.map((node) => {
          switch (node.kind) {
            case "marker":
              return <TimelineMinuteMarker key={node.key} ts={node.ts} />
            case "event":
              return (
                <TimelineEvent
                  key={node.key}
                  event={node.event}
                  onFlagClick={onFlagClick}
                />
              )
            case "group":
              return (
                <TimelineGroup
                  key={node.key}
                  groupKey={node.groupKey}
                  tool={node.tool}
                  events={node.events}
                >
                  <TimelineGroup.Summary />
                  <TimelineGroup.Details />
                </TimelineGroup>
              )
          }
        })}
      </ol>
    </section>
  )
}

// ── Grouping passes ─────────────────────────────────────────────────────────
// Pass 1: bucket by minute (HH:MM, UTC). Minute boundary is a hard visual
//         separator — groups never cross it (SESSION-DETAIL-V1.md §8 q2).
// Pass 2: within each minute, walk events; coalesce consecutive runs sharing
//         `group_key` (or `tool_name` fallback) into TimelineGroup nodes if
//         the run length is ≥ MIN_GROUP_SIZE. Otherwise emit individual events.
// Pass 3: flatten into a node list with one marker per minute boundary first.

export function buildNodes(events: SessionEvent[]): TimelineNode[] {
  if (events.length === 0) return []
  const minutes = bucketByMinute(events)
  const out: TimelineNode[] = []
  for (const [minuteKey, bucket] of minutes) {
    out.push({ kind: "marker", key: `marker-${minuteKey}`, ts: bucket[0].at })
    const runs = collapseRuns(bucket)
    for (const run of runs) {
      if (run.events.length >= MIN_GROUP_SIZE && run.groupable) {
        out.push({
          kind: "group",
          key: `group-${run.groupKey}`,
          groupKey: run.groupKey,
          tool: run.tool,
          events: run.events,
        })
      } else {
        for (const event of run.events) {
          out.push({ kind: "event", key: `event-${event.id}`, event })
        }
      }
    }
  }
  return out
}

function bucketByMinute(events: SessionEvent[]): Map<string, SessionEvent[]> {
  const out = new Map<string, SessionEvent[]>()
  for (const e of events) {
    const key = minuteKey(e.at)
    const bucket = out.get(key)
    if (bucket) bucket.push(e)
    else out.set(key, [e])
  }
  return out
}

function minuteKey(at: string): string {
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return at
  // YYYY-MM-DDTHH:MM (UTC) — chronologically sortable AND unique per minute.
  return d.toISOString().slice(0, 16)
}

interface Run {
  tool: string
  groupKey: string
  events: SessionEvent[]
  groupable: boolean
}

function collapseRuns(events: SessionEvent[]): Run[] {
  const runs: Run[] = []
  for (const event of events) {
    const key = groupingKey(event)
    const tool = toolLabel(event)
    const groupable = groupableEvent(event)
    const last = runs[runs.length - 1]
    if (
      last &&
      last.groupable &&
      groupable &&
      key !== null &&
      last.groupKey === key &&
      last.tool === tool
    ) {
      last.events.push(event)
    } else {
      runs.push({
        tool,
        groupKey: key ?? `solo-${event.id}`,
        events: [event],
        groupable: groupable && key !== null,
      })
    }
  }
  return runs
}

function groupingKey(event: SessionEvent): string | null {
  if (event.group_key) return event.group_key
  if (event.type === "tool_call") {
    const tool = event.tool ?? event.tool_name
    if (tool) return `tool:${tool}:${minuteKey(event.at)}`
  }
  return null
}

function toolLabel(event: SessionEvent): string {
  if (event.type === "tool_call") return event.tool ?? event.tool_name ?? "tool"
  if (event.type === "file_change") return event.file_op ?? "edit"
  if (event.type === "error") return "err"
  return "msg"
}

function groupableEvent(event: SessionEvent): boolean {
  // Flag rows are never grouped (per §3 — flag rows are always expanded).
  if (event.flag) return false
  // Errors and messages are individually meaningful — never collapse.
  if (event.type === "error" || event.type === "message") return false
  return true
}
