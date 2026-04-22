import { forwardRef, useId } from "react"
import type { EventType, SessionEvent } from "./types"

// Swiss chrome band: single `border-b border-rule` rule, no nested card.
// Three primary controls (type chips, search, flags-only) + keyboard hints.
// Counts next to each chip so a user skimming knows "Bash ×12, Edit ×8".

export type MessageSubtype = "user" | "assistant" | "thinking" | "notification" | "subagent"

export interface TimelineFilters {
  /** Active event-type filter. `null` = all. */
  type: EventType | null
  /** Message-subtype filter (applies only when type="message" or null). */
  subtype: MessageSubtype | null
  /** Tool-name filter (Bash / Edit / Read / …). `null` = all tools. */
  toolName: string | null
  /** Case-insensitive substring search over tool/path/content. */
  query: string
  /** Hide non-flagged events when true. */
  flagsOnly: boolean
}

export const EMPTY_FILTERS: TimelineFilters = {
  type: null,
  subtype: null,
  toolName: null,
  query: "",
  flagsOnly: false,
}

interface TimelineFilterBarProps {
  events: SessionEvent[]
  filters: TimelineFilters
  onChange: (next: TimelineFilters) => void
  /** Count after filtering, shown as `N / M events`. */
  filteredCount: number
  /** Total event count before filtering. */
  totalCount: number
}

const TYPE_LABELS: Record<EventType, string> = {
  tool_call:   "[tool]",
  file_change: "[file]",
  error:       "[err]",
  message:     "[msg]",
}

const TYPE_CLASSES: Record<EventType, string> = {
  tool_call:   "text-accent-500",
  file_change: "text-ink-muted",
  error:       "text-flag-env-fg",
  message:     "text-ink-faint",
}

export const TimelineFilterBar = forwardRef<HTMLInputElement, TimelineFilterBarProps>(
  function TimelineFilterBar(
    { events, filters, onChange, filteredCount, totalCount },
    searchRef,
  ) {
    const searchId = useId()

    // Counts per type (pre-filter, so the chip counts never look empty).
    const countsByType: Record<EventType, number> = {
      tool_call: 0,
      file_change: 0,
      error: 0,
      message: 0,
    }
    // Counts per message subtype — only relevant for the "conversation" row.
    const countsBySubtype: Record<MessageSubtype, number> = {
      user: 0, assistant: 0, thinking: 0, notification: 0, subagent: 0,
    }
    // Counts per tool name (Bash / Edit / Read / …). Covers both tool_call
    // and file_change events so the user can pivot on "only Edit" etc.
    // MCP tools (prefix mcp__) are collapsed under a single "MCP" bucket
    // to avoid dozens of tiny chips.
    const countsByTool = new Map<string, number>()
    for (const e of events) {
      countsByType[e.type] = (countsByType[e.type] ?? 0) + 1
      if (e.type === "message") {
        const sub = (e.tool ?? e.tool_name) as MessageSubtype | undefined
        if (sub && sub in countsBySubtype) countsBySubtype[sub]++
      } else if (e.type === "tool_call" || e.type === "file_change") {
        const rawName = e.tool ?? e.tool_name
        if (!rawName) continue
        const name = rawName.startsWith("mcp__") ? "MCP" : rawName
        countsByTool.set(name, (countsByTool.get(name) ?? 0) + 1)
      }
    }
    const toolChips = [...countsByTool.entries()].sort((a, b) => b[1] - a[1])

    const flagCount = events.reduce((n, e) => n + (e.flag ? 1 : 0), 0)

    // Any filter active? Used to show the "clear" button + reset all state.
    const anyFilterActive =
      filters.type !== null ||
      filters.subtype !== null ||
      filters.toolName !== null ||
      filters.flagsOnly ||
      filters.query.trim() !== ""

    return (
      <div
        aria-label="Timeline filters"
        className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule px-4 py-2"
      >
        {/* type chips — click to filter, click again to clear */}
        <div role="group" aria-label="Filter by event type" className="flex items-center gap-1.5">
          {(["tool_call", "file_change", "error", "message"] as EventType[]).map((t) => {
            const active = filters.type === t
            const count = countsByType[t] ?? 0
            const disabled = count === 0
            return (
              <button
                key={t}
                type="button"
                disabled={disabled}
                onClick={() => onChange({ ...filters, type: active ? null : t })}
                aria-pressed={active}
                className={
                  "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 " +
                  "font-mono text-micro tabular-nums tracking-wider " +
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
                  "focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
                  (active
                    ? "border-accent-500 bg-accent-500/10 " + TYPE_CLASSES[t]
                    : disabled
                      ? "border-rule text-ink-faint opacity-50 cursor-not-allowed"
                      : "border-rule text-ink-muted hover:text-ink hover:border-ink-faint " + TYPE_CLASSES[t])
                }
              >
                <span>{TYPE_LABELS[t]}</span>
                <span className="text-ink-faint">{count}</span>
              </button>
            )
          })}
        </div>

        {/* message subtype chips — separate row so types and subtypes don't
            conflict visually; each button acts as a "show only X" filter. */}
        {countsByType.message > 0 && (
          <div role="group" aria-label="Filter by message subtype" className="flex items-center gap-1.5">
            {(["user", "assistant", "thinking", "notification", "subagent"] as MessageSubtype[]).map((s) => {
              const active = filters.subtype === s
              const count = countsBySubtype[s] ?? 0
              if (count === 0) return null
              const label = s === "user" ? "[you]"
                : s === "assistant" ? "[bot]"
                  : s === "thinking" ? "[thk]"
                    : s === "notification" ? "[note]"
                      : "[sub]"
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => onChange({ ...filters, subtype: active ? null : s, type: active ? filters.type : "message" })}
                  aria-pressed={active}
                  className={
                    "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 " +
                    "font-mono text-micro tabular-nums tracking-wider " +
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
                    "focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
                    (active
                      ? "border-accent-500 bg-accent-500/10 text-ink"
                      : "border-rule text-ink-muted hover:text-ink hover:border-ink-faint")
                  }
                >
                  <span>{label}</span>
                  <span className="text-ink-faint">{count}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* flags-only toggle */}
        <button
          type="button"
          disabled={flagCount === 0}
          onClick={() => onChange({ ...filters, flagsOnly: !filters.flagsOnly })}
          aria-pressed={filters.flagsOnly}
          title="Toggle flags-only (f)"
          className={
            "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 " +
            "font-mono text-micro tabular-nums tracking-wider " +
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
            "focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
            (filters.flagsOnly
              ? "border-flag-secret bg-flag-secret-bg/40 text-flag-secret-fg"
              : flagCount === 0
                ? "border-rule text-ink-faint opacity-50 cursor-not-allowed"
                : "border-rule text-ink-muted hover:text-ink hover:border-ink-faint")
          }
        >
          <span>flags only</span>
          <span className="text-ink-faint">{flagCount}</span>
        </button>

        {/* tool-name chips — one row, sorted by count, wraps on narrow.
            Clicking a tool chip filters events to that tool only (Bash /
            Edit / Read / Write / WebFetch / …). MCP tools coalesced. */}
        {toolChips.length > 0 && (
          <div
            role="group"
            aria-label="Filter by tool"
            className="basis-full flex flex-wrap items-center gap-1 border-t border-dashed border-rule pt-2"
          >
            <span className="shrink-0 font-mono text-micro uppercase tracking-wider text-ink-faint pr-1">
              tool
            </span>
            {toolChips.map(([name, count]) => {
              const active = filters.toolName === name
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => onChange({ ...filters, toolName: active ? null : name })}
                  aria-pressed={active}
                  className={
                    "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 " +
                    "font-mono text-micro tabular-nums " +
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
                    "focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
                    (active
                      ? "border-accent-500 bg-accent-500/10 text-ink"
                      : "border-rule text-ink-muted hover:text-ink hover:border-ink-faint")
                  }
                >
                  <span>{name}</span>
                  <span className="text-ink-faint">{count}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* search input — grows to fill, `/` shortcut focuses it */}
        <label htmlFor={searchId} className="sr-only">
          Search events
        </label>
        <input
          ref={searchRef}
          id={searchId}
          type="search"
          value={filters.query}
          onChange={(e) => onChange({ ...filters, query: e.target.value })}
          placeholder="/ to search path, tool, content…"
          className={
            "min-w-0 flex-1 rounded-sm border border-rule bg-sunken px-2 py-0.5 " +
            "font-mono text-caption text-ink placeholder:text-ink-faint " +
            "focus:border-accent-500 focus:outline-none focus:ring-0"
          }
        />

        {/* filtered count + clear-all */}
        <span className="shrink-0 font-mono text-micro tabular-nums text-ink-faint">
          {filteredCount === totalCount
            ? `${totalCount} event${totalCount === 1 ? "" : "s"}`
            : `${filteredCount} / ${totalCount}`}
        </span>
        {anyFilterActive && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            title="Clear all filters (esc)"
            className={
              "shrink-0 rounded-sm border border-accent-500/50 bg-accent-500/10 px-1.5 py-0.5 " +
              "font-mono text-micro uppercase tracking-wider text-accent-500 " +
              "hover:bg-accent-500/20 " +
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
              "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
            }
          >
            ✕ clear
          </button>
        )}
      </div>
    )
  },
)

/** Pure predicate — apply filters to an event list. Memo-friendly. */
export function filterEvents(events: SessionEvent[], f: TimelineFilters): SessionEvent[] {
  if (
    f.type === null &&
    f.subtype === null &&
    f.toolName === null &&
    !f.query &&
    !f.flagsOnly
  ) return events
  const q = f.query.trim().toLowerCase()
  return events.filter((e) => {
    if (f.type !== null && e.type !== f.type) return false
    if (f.subtype !== null) {
      // subtype only applies to message events. If filtering by subtype
      // implicitly also restrict to type=message.
      if (e.type !== "message") return false
      const sub = e.tool ?? e.tool_name
      if (sub !== f.subtype) return false
    }
    if (f.toolName !== null) {
      const rawName = e.tool ?? e.tool_name
      if (!rawName) return false
      const name = rawName.startsWith("mcp__") ? "MCP" : rawName
      if (name !== f.toolName) return false
    }
    if (f.flagsOnly && !e.flag) return false
    if (q) {
      const hay = [
        e.tool,
        e.tool_name,
        e.path,
        e.file_path,
        e.content,
        e.output,
        e.text,
        e.error_message,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}
