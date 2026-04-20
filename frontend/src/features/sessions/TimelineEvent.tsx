import type { SessionEvent, FileOp } from "../../types/receipt"
import { formatRelative } from "../../lib/format"
import { RedFlagBadge } from "./RedFlagBadge"

interface TimelineEventProps {
  event: SessionEvent
  expanded: boolean
  onToggle: () => void
  onFlagClick: () => void
}

const OP_STYLE: Record<FileOp, string> = {
  create: "bg-emerald-900/30 text-emerald-200 ring-emerald-900/50",
  edit:   "bg-accent-900/30 text-accent-200 ring-accent-900/50",
  delete: "bg-flag-env-bg text-flag-env-fg ring-flag-env",
}

const OP_LABEL: Record<FileOp, string> = {
  create: "create",
  edit:   "edit",
  delete: "delete",
}

export function TimelineEvent({
  event,
  expanded,
  onToggle,
  onFlagClick,
}: TimelineEventProps) {
  return (
    <li className="relative pl-10">
      <Dot type={event.type} />
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Body
            event={event}
            expanded={expanded}
            onToggle={onToggle}
          />
        </div>
        <time
          className="shrink-0 font-mono text-micro text-ink-faint"
          title={event.at}
          dateTime={event.at}
        >
          {formatRelative(event.at)}
        </time>
      </div>
      {event.flag && (
        <div className="mt-1.5">
          <RedFlagBadge kind={event.flag} onClick={onFlagClick} />
        </div>
      )}
    </li>
  )
}

function Dot({ type }: { type: SessionEvent["type"] }) {
  const { ch, ring } = DOT_STYLE[type]
  return (
    <span
      aria-hidden="true"
      className={
        "absolute left-0 top-0.5 flex h-6 w-6 items-center justify-center " +
        "rounded-full bg-surface font-mono text-caption ring-1 " +
        ring
      }
    >
      {ch}
    </span>
  )
}

const DOT_STYLE: Record<
  SessionEvent["type"],
  { ch: string; ring: string }
> = {
  tool_call:   { ch: "▶", ring: "ring-accent-500 text-accent-500" },
  file_change: { ch: "✎", ring: "ring-ink-muted text-ink-muted" },
  error:       { ch: "!", ring: "ring-flag-env text-flag-env-fg" },
  message:     { ch: "“", ring: "ring-rule text-ink-muted" },
}

interface BodyProps {
  event: SessionEvent
  expanded: boolean
  onToggle: () => void
}

function Body({ event, expanded, onToggle }: BodyProps) {
  switch (event.type) {
    case "tool_call":
      return <ToolCallBody event={event} expanded={expanded} onToggle={onToggle} />
    case "file_change":
      return <FileChangeBody event={event} />
    case "error":
      return <ErrorBody event={event} expanded={expanded} onToggle={onToggle} />
    case "message":
      return <MessageBody event={event} />
  }
}

function ToolCallBody({ event, expanded, onToggle }: BodyProps) {
  const preview = toolInputPreview(event.tool_input)
  const full = formatJson(event.tool_input)
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="group flex w-full items-baseline gap-2 text-left focus-visible:outline-none"
      >
        <span className="font-mono text-caption font-semibold text-ink">
          {event.tool_name ?? "tool"}
        </span>
        {!expanded && preview && (
          <span className="truncate font-mono text-caption text-ink-muted group-hover:text-ink">
            {preview}
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-micro text-ink-faint">
          {expanded ? "−" : "+"}
        </span>
      </button>
      {expanded && full && (
        <pre className="mt-2 max-h-80 overflow-auto rounded-sm bg-sunken p-3 font-mono text-micro leading-relaxed text-ink-muted">
          {full}
        </pre>
      )}
    </div>
  )
}

function FileChangeBody({ event }: { event: SessionEvent }) {
  const op = (event.file_op ?? "edit") as FileOp
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className={
          "inline-flex items-center rounded-sm px-1.5 py-0.5 " +
          "font-mono text-micro font-semibold uppercase tracking-wider ring-1 ring-inset " +
          OP_STYLE[op]
        }
      >
        {OP_LABEL[op]}
      </span>
      <span className="truncate font-mono text-caption text-ink">
        {event.file_path ?? "(unknown path)"}
      </span>
    </div>
  )
}

function ErrorBody({ event, expanded, onToggle }: BodyProps) {
  const message = event.error_message ?? "Error"
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="group flex w-full items-baseline gap-2 text-left focus-visible:outline-none"
      >
        <span className="truncate font-mono text-caption text-flag-env-fg group-hover:underline">
          {message}
        </span>
        <span className="ml-auto shrink-0 font-mono text-micro text-ink-faint">
          {expanded ? "−" : "+"}
        </span>
      </button>
      {expanded && (
        <pre className="mt-2 max-h-64 overflow-auto rounded-sm bg-sunken p-3 font-mono text-micro leading-relaxed text-flag-env-fg/80">
          {message}
          {"\n\n(stack trace not available in v0 — full trail on backend)"}
        </pre>
      )}
    </div>
  )
}

function MessageBody({ event }: { event: SessionEvent }) {
  return (
    <blockquote className="border-l-2 border-rule pl-2 font-mono text-caption italic text-ink-muted">
      {event.text ?? "(empty message)"}
    </blockquote>
  )
}

function toolInputPreview(input: unknown): string {
  const s = formatJson(input)
  if (!s) return ""
  const collapsed = s.replace(/\s+/g, " ").trim()
  return collapsed.length > 80 ? collapsed.slice(0, 80) + "…" : collapsed
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
