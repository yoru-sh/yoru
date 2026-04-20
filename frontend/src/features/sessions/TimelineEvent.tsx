import { memo, useState } from "react"
import type { EventType, SessionEvent } from "../../types/receipt"
import { RedFlagBadge } from "./RedFlagBadge"

interface TimelineEventProps {
  event: SessionEvent
  /** When true, render with a left rule + indent — used inside <TimelineGroup.Details>. */
  nested?: boolean
  onFlagClick?: () => void
}

// Glyph per kind. The glyph IS the verb (no decorative icons) — SESSION-DETAIL-V1 §3.
const GLYPH: Record<EventType, string> = {
  tool_call:   "▶",
  file_change: "✎",
  error:       "✉",
  message:     "✉",
}

// SR-only verb behind the glyph (which is aria-hidden).
const VERB: Record<EventType, string> = {
  tool_call:   "ran",
  file_change: "wrote",
  error:       "errored",
  message:     "messaged",
}

function TimelineEventImpl({ event, nested = false, onFlagClick }: TimelineEventProps) {
  const [open, setOpen] = useState(false)
  const expandable = hasExpandableContent(event)
  const toggle = () => {
    if (expandable) setOpen((v) => !v)
  }

  const label = labelFor(event)
  const primary = primaryFor(event)
  const meta = metaFor(event)
  const isFlag = event.type === "tool_call" && !!event.flag

  return (
    <li
      id={`event-${event.id}`}
      className={
        "motion-safe:animate-feed-in list-none border-b border-dashed border-rule last:border-b-0 " +
        (nested ? "pl-6 border-l border-rule" : "")
      }
    >
      <div
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? open : undefined}
        onClick={toggle}
        onKeyDown={(e) => {
          if (!expandable) return
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            toggle()
          }
        }}
        className={
          "group flex items-center gap-2 min-h-8 py-1 " +
          "hover:bg-sunken/40 focus-within:bg-sunken/40 " +
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper rounded-sm " +
          (expandable ? "cursor-pointer" : "")
        }
      >
        <span aria-hidden="true" className="w-4 shrink-0 font-mono text-ink text-center">
          {GLYPH[event.type]}
        </span>
        <span className="sr-only">{VERB[event.type]}</span>
        <span className="w-14 shrink-0 font-sans text-caption uppercase tracking-wider text-ink-muted truncate">
          {label}
        </span>
        <span
          className="flex-1 min-w-0 font-mono text-sm text-ink truncate"
          title={primary}
        >
          {primary || <span className="text-ink-faint">(no payload)</span>}
        </span>
        {isFlag && event.flag && (
          <span className="shrink-0">
            <RedFlagBadge kind={event.flag} onClick={onFlagClick} />
          </span>
        )}
        <span className="shrink-0 font-mono text-caption text-ink-faint tabular-nums whitespace-nowrap">
          {meta}
        </span>
        {expandable && (
          <span
            aria-hidden="true"
            className="shrink-0 w-4 text-center font-mono text-micro text-ink-faint group-hover:text-ink"
          >
            {open ? "−" : "+"}
          </span>
        )}
      </div>
      {expandable && open && (
        <pre className="mt-1 mb-2 max-h-80 overflow-auto rounded-sm bg-sunken p-3 font-mono text-sm leading-relaxed text-ink">
          {expandedContent(event)}
        </pre>
      )}
    </li>
  )
}

export const TimelineEvent = memo(TimelineEventImpl)

// ── Grammar helpers ─────────────────────────────────────────────────────────

function labelFor(event: SessionEvent): string {
  switch (event.type) {
    case "tool_call":
      return event.tool ?? event.tool_name ?? "tool"
    case "file_change":
      return event.file_op ?? "edit"
    case "error":
      return "err"
    case "message":
      return "msg"
  }
}

function primaryFor(event: SessionEvent): string {
  switch (event.type) {
    case "tool_call": {
      // Prefer explicit content (e.g. Bash command, Grep pattern); fall back to a
      // best-effort one-liner from tool_input. Truncation handled by CSS .truncate.
      if (event.content && event.content.trim()) return collapseWhitespace(event.content)
      if (event.path) return event.path
      return toolInputOneLiner(event.tool_input) || ""
    }
    case "file_change":
      return event.path ?? event.file_path ?? "(unknown path)"
    case "error":
      return event.error_message ?? "Error"
    case "message":
      return event.text ?? ""
  }
}

function metaFor(event: SessionEvent): string {
  if (event.type === "tool_call" || event.type === "file_change") {
    return formatDurationMs(event.duration_ms)
  }
  return ""
}

function hasExpandableContent(event: SessionEvent): boolean {
  if (event.content && event.content.length > 0) return true
  if (event.tool_input !== undefined && event.tool_input !== null) return true
  if (event.type === "error" && event.error_message) return true
  if (event.type === "message" && event.text && event.text.length > 80) return true
  if (event.output && event.output.length > 0) return true
  return false
}

function expandedContent(event: SessionEvent): string {
  const parts: string[] = []
  if (event.content) parts.push(event.content)
  if (event.tool_input !== undefined && event.tool_input !== null) {
    parts.push(formatJson(event.tool_input))
  }
  if (event.output) {
    parts.push("─── output ───")
    parts.push(event.output)
  }
  if (event.type === "error" && event.error_message && parts.length === 0) {
    parts.push(event.error_message)
  }
  if (event.type === "message" && event.text && parts.length === 0) {
    parts.push(event.text)
  }
  return parts.join("\n\n")
}

export function formatDurationMs(ms: number | undefined): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return ""
  if (ms < 1) return ""
  if (ms < 1000) return `${Math.round(ms)}ms`
  const s = ms / 1000
  if (s < 10) return `${s.toFixed(1)}s`
  return `${Math.round(s)}s`
}

function collapseWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim()
}

function toolInputOneLiner(input: unknown): string {
  if (input === undefined || input === null) return ""
  if (typeof input === "string") return collapseWhitespace(input)
  try {
    const obj = input as Record<string, unknown>
    // Best-effort priority order — most tool schemas surface one of these.
    const candidates = ["command", "pattern", "file_path", "path", "query", "url"]
    for (const k of candidates) {
      const v = obj[k]
      if (typeof v === "string" && v.length > 0) return collapseWhitespace(v)
    }
    return collapseWhitespace(JSON.stringify(input))
  } catch {
    return ""
  }
}

function formatJson(input: unknown): string {
  if (input === undefined || input === null) return ""
  if (typeof input === "string") return input
  try {
    return JSON.stringify(input, null, 2)
  } catch {
    return String(input)
  }
}
