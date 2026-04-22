import type { SessionEvent } from "./types"
import { redactTokens } from "./redact"
import { CodeBlock, langFromPath, type CodeLang } from "./CodeBlock"
import { Markdown } from "./Markdown"

// Tool-aware expanded renderer. Routes per `event.tool` to a shape that
// matches the tool's natural idiom (shell prompt for Bash, stacked diff for
// Edit, JSON tree for MCP). Generic JSON fallback for anything else so we
// never show an empty expand.
//
// Design: one-file-registry. Each renderer is a small local component; the
// public `<ExpandedBody event={event} />` picks the right one. Keeps the
// surface navigable from a single file while letting each variant stay
// single-purpose.

interface ExpandedBodyProps {
  event: SessionEvent
}

export function ExpandedBody({ event }: ExpandedBodyProps) {
  const tool = event.tool ?? event.tool_name
  const raw = (event.tool_input ?? {}) as Record<string, unknown>
  // Fallback for each tool — when `tool_input` is missing from the server
  // (old events, pre-tool_input serialization) the backend-extracted
  // `content` still carries the primary string (command, pattern, path…).
  const contentFallback = event.content ?? ""

  if (event.type === "error") {
    return <ErrorBody message={event.error_message ?? event.content ?? ""} output={event.output} />
  }
  if (event.type === "message") {
    const sub = (event.tool ?? event.tool_name ?? "") as string
    const known = ["user", "assistant", "thinking", "notification", "subagent"]
    return (
      <MessageBody
        text={event.text ?? event.content ?? ""}
        subtype={known.includes(sub) ? (sub as "user" | "assistant" | "thinking" | "notification" | "subagent") : undefined}
      />
    )
  }
  // Both tool_call and file_change route by `tool` so Edit/Write/MultiEdit
  // always render their diff view — the backend tags writer tools with
  // kind=file_change via _infer_kind, so filtering on `type === "tool_call"`
  // alone dropped diffs from the expanded view. FileChangeBody stays the
  // fallback for untooled legacy file_change rows (test fixtures).
  switch (tool) {
    case "Bash":
    case "Shell":
      return <BashBody raw={raw} fallback={contentFallback} output={event.output} />
    case "Edit":
      return <EditDiffBody raw={raw} output={event.output} />
    case "MultiEdit":
      return <MultiEditBody raw={raw} output={event.output} />
    case "Write":
      return <WriteBody raw={raw} output={event.output} />
    case "NotebookEdit":
      return <EditDiffBody raw={raw} output={event.output} />
    case "Read":
      return <ReadBody raw={raw} fallback={contentFallback} output={event.output} />
    case "Grep":
      return <GrepBody raw={raw} fallback={contentFallback} output={event.output} />
    case "Glob":
      return <GlobBody raw={raw} fallback={contentFallback} output={event.output} />
    case "WebFetch":
    case "WebSearch":
      return <WebBody tool={tool} raw={raw} fallback={contentFallback} output={event.output} />
    case "Task":
      return <TaskBody raw={raw} fallback={contentFallback} output={event.output} />
    case "TodoWrite":
      return <TodoBody raw={raw} />
    default:
      if (event.type === "file_change") {
        return <FileChangeBody event={event} raw={raw} />
      }
      return <JsonBody raw={raw} output={event.output} />
  }
}

// ── Primitives ──────────────────────────────────────────────────────────────

function Rubric({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1 font-mono text-micro uppercase tracking-wider text-ink-faint">
      {children}
    </p>
  )
}

function Section({ children }: { children: React.ReactNode }) {
  return <section className="py-2 first:pt-0 last:pb-0">{children}</section>
}

// Thin alias kept for source compat with the previous CodePre usage inside
// this file. `lang="text"` → redacted <pre>; other langs go through Prism.
function CodePre({
  children,
  className = "",
  lang = "text",
}: {
  children: string
  className?: string
  lang?: CodeLang
}) {
  return (
    <CodeBlock lang={lang} className={className}>
      {children}
    </CodeBlock>
  )
}

function PathLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2 font-mono text-sm">
      <span className="shrink-0 text-micro uppercase tracking-wider text-ink-faint">
        {label}
      </span>
      <code className="min-w-0 truncate rounded-sm bg-sunken px-1.5 py-0.5 text-ink">
        {value || "—"}
      </code>
    </div>
  )
}

// Auto-detect a Prism language for tool output. Priority:
//   1. explicit `hint` from the renderer (e.g. Read passes the file's lang)
//   2. JSON shape (starts with { or [)
//   3. markdown shape (starts with # or has ``` fences)
//   4. diff shape (lines starting with +++ / --- / @@)
//   5. text fallback
function detectOutputLang(output: string, hint?: CodeLang): CodeLang {
  if (hint && hint !== "text") return hint
  const trimmed = output.trimStart()
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      JSON.parse(trimmed)
      return "json"
    } catch {
      /* not valid JSON, fall through */
    }
  }
  if (/^(?:#{1,6}\s|```)/m.test(trimmed)) return "markdown"
  if (/^(?:\+\+\+|---|@@)/m.test(trimmed)) return "diff"
  return "text"
}

function OutputBlock({ output, hint }: { output?: string; hint?: CodeLang }) {
  if (!output) return null
  const lang = detectOutputLang(output, hint)
  return (
    <Section>
      <Rubric>§ output{lang !== "text" ? ` · ${lang}` : ""}</Rubric>
      <CodePre lang={lang}>{output}</CodePre>
    </Section>
  )
}

// ── Tool-specific ───────────────────────────────────────────────────────────

function BashBody({
  raw,
  fallback,
  output,
}: {
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const cmd = asString(raw.command) || fallback
  return (
    <>
      <Section>
        <Rubric>§ command</Rubric>
        <CodePre lang="bash">{cmd ? `$ ${cmd}` : "(no command)"}</CodePre>
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function EditDiffBody({
  raw,
  output,
}: {
  raw: Record<string, unknown>
  output?: string
}) {
  const path = asString(raw.file_path)
  const oldStr = asString(raw.old_string)
  const newStr = asString(raw.new_string)
  const lang = langFromPath(path)
  return (
    <>
      {path && (
        <Section>
          <PathLine label="path" value={path} />
        </Section>
      )}
      {oldStr && (
        <Section>
          <Rubric>− old</Rubric>
          <CodePre lang={lang} className="border-l-2 border-flag-env/60">{oldStr}</CodePre>
        </Section>
      )}
      {newStr && (
        <Section>
          <Rubric>+ new</Rubric>
          <CodePre lang={lang} className="border-l-2 border-op-create/60">{newStr}</CodePre>
        </Section>
      )}
      {!oldStr && !newStr && <JsonBody raw={raw} output={undefined} />}
      <OutputBlock output={output} />
    </>
  )
}

function MultiEditBody({
  raw,
  output,
}: {
  raw: Record<string, unknown>
  output?: string
}) {
  const path = asString(raw.file_path)
  const edits = Array.isArray(raw.edits) ? raw.edits : []
  const lang = langFromPath(path)
  return (
    <>
      {path && (
        <Section>
          <PathLine label="path" value={path} />
        </Section>
      )}
      <Section>
        <Rubric>§ {edits.length} edit{edits.length === 1 ? "" : "s"}</Rubric>
        <ol className="space-y-2">
          {edits.map((raw, i) => {
            const ed = (raw ?? {}) as Record<string, unknown>
            const oldStr = asString(ed.old_string)
            const newStr = asString(ed.new_string)
            return (
              <li key={i} className="rounded-sm border border-dashed border-rule p-2">
                <p className="mb-1 font-mono text-micro text-ink-faint">#{i + 1}</p>
                {oldStr && <CodePre lang={lang} className="border-l-2 border-flag-env/60 mb-1">{oldStr}</CodePre>}
                {newStr && <CodePre lang={lang} className="border-l-2 border-op-create/60">{newStr}</CodePre>}
              </li>
            )
          })}
        </ol>
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function WriteBody({ raw, output }: { raw: Record<string, unknown>; output?: string }) {
  const path = asString(raw.file_path)
  const content = asString(raw.content)
  const lang = langFromPath(path)
  return (
    <>
      {path && (
        <Section>
          <PathLine label="path" value={path} />
        </Section>
      )}
      {content && (
        <Section>
          <Rubric>§ content ({content.split("\n").length} lines)</Rubric>
          <CodePre lang={lang} className="border-l-2 border-op-create/60">{content}</CodePre>
        </Section>
      )}
      <OutputBlock output={output} />
    </>
  )
}

function ReadBody({
  raw,
  fallback,
  output,
}: {
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const path = asString(raw.file_path) || fallback
  // Output = file content → highlight using the file's own language.
  const hint = langFromPath(path)
  return (
    <>
      <Section>
        <PathLine label="path" value={path} />
      </Section>
      <OutputBlock output={output} hint={hint} />
    </>
  )
}

function GrepBody({
  raw,
  fallback,
  output,
}: {
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const pattern = asString(raw.pattern) || fallback
  const path = asString(raw.path)
  const glob = asString(raw.glob)
  return (
    <>
      <Section>
        <PathLine label="pattern" value={pattern} />
        {path && <PathLine label="in" value={path} />}
        {glob && <PathLine label="glob" value={glob} />}
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function GlobBody({
  raw,
  fallback,
  output,
}: {
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const pattern = asString(raw.pattern) || fallback
  const path = asString(raw.path)
  return (
    <>
      <Section>
        <PathLine label="glob" value={pattern} />
        {path && <PathLine label="in" value={path} />}
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function WebBody({
  tool,
  raw,
  fallback,
  output,
}: {
  tool: string
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const url = asString(raw.url) || (tool === "WebFetch" ? fallback : "")
  const query = asString(raw.query) || (tool === "WebSearch" ? fallback : "")
  const prompt = asString(raw.prompt)
  return (
    <>
      <Section>
        {tool === "WebFetch" && url && <PathLine label="url" value={url} />}
        {tool === "WebSearch" && query && <PathLine label="query" value={query} />}
        {prompt && (
          <div className="mt-2">
            <Rubric>§ prompt</Rubric>
            <CodePre>{prompt}</CodePre>
          </div>
        )}
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function TaskBody({
  raw,
  fallback,
  output,
}: {
  raw: Record<string, unknown>
  fallback: string
  output?: string
}) {
  const desc = asString(raw.description) || fallback
  const prompt = asString(raw.prompt)
  const subagentType = asString(raw.subagent_type)
  return (
    <>
      <Section>
        {subagentType && <PathLine label="agent" value={subagentType} />}
        {desc && <PathLine label="task" value={desc} />}
      </Section>
      {prompt && (
        <Section>
          <Rubric>§ prompt</Rubric>
          <CodePre>{prompt}</CodePre>
        </Section>
      )}
      <OutputBlock output={output} />
    </>
  )
}

interface Todo {
  content?: string
  activeForm?: string
  status?: string
}

function TodoBody({ raw }: { raw: Record<string, unknown> }) {
  const todos = Array.isArray(raw.todos) ? (raw.todos as Todo[]) : []
  if (todos.length === 0) return <JsonBody raw={raw} output={undefined} />
  return (
    <Section>
      <Rubric>§ {todos.length} todo{todos.length === 1 ? "" : "s"}</Rubric>
      <ul className="space-y-1">
        {todos.map((t, i) => {
          const status = (t.status ?? "pending").toLowerCase()
          const mark =
            status === "completed" ? "✓" : status === "in_progress" ? "▸" : "·"
          const klass =
            status === "completed"
              ? "text-ink-faint line-through"
              : status === "in_progress"
                ? "text-accent-500"
                : "text-ink"
          return (
            <li key={i} className="flex items-baseline gap-2 font-mono text-sm">
              <span className={"w-4 shrink-0 text-center " + klass}>{mark}</span>
              <span className={"min-w-0 " + klass}>{t.content ?? t.activeForm ?? "(untitled)"}</span>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

function JsonBody({ raw, output }: { raw: unknown; output?: string }) {
  const pretty = safeJsonStringify(raw)
  return (
    <>
      {pretty && (
        <Section>
          <Rubric>§ input</Rubric>
          <CodePre lang="json">{pretty}</CodePre>
        </Section>
      )}
      <OutputBlock output={output} />
    </>
  )
}

function FileChangeBody({
  event,
  raw,
}: {
  event: SessionEvent
  raw: Record<string, unknown>
}) {
  const path = event.path ?? event.file_path ?? asString(raw.file_path)
  const op = event.file_op ?? "edit"
  return (
    <Section>
      <div className="flex items-baseline gap-2 font-mono text-sm">
        <span className="shrink-0 rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-micro font-semibold uppercase tracking-wider text-ink-muted">
          {op}
        </span>
        <code className="min-w-0 truncate text-ink">{path ?? "(unknown path)"}</code>
      </div>
    </Section>
  )
}

function ErrorBody({ message, output }: { message: string; output?: string }) {
  return (
    <>
      <Section>
        <Rubric>§ error</Rubric>
        <CodePre className="border-l-2 border-flag-env/60">{message || "(no message)"}</CodePre>
      </Section>
      <OutputBlock output={output} />
    </>
  )
}

function MessageBody({
  text,
  subtype,
}: {
  text: string
  subtype?: "user" | "assistant" | "thinking" | "notification" | "subagent"
}) {
  const safe = redactTokens(text)
  const isMultiLine = safe.includes("\n") || safe.length > 140
  const isConversation = subtype === "user" || subtype === "assistant"
  // Claude's responses are markdown by convention (headings, lists, code
  // fences, bold). User prompts often are too (pasted snippets). Render them
  // through react-markdown so the audit view is actually readable, not a
  // raw-text wall. Thinking/notification/subagent stay as italic blockquotes
  // since they're internal/system and usually plain text.
  const renderAsMarkdown = subtype === "user" || subtype === "assistant"
  const borderClass =
    subtype === "user"
      ? "border-accent-500/70"
      : subtype === "assistant"
        ? "border-accent-500/40"
        : subtype === "thinking"
          ? "border-ink-faint"
          : "border-rule"

  if (renderAsMarkdown) {
    return (
      <Section>
        <div
          className={
            "max-h-96 overflow-y-auto rounded-sm bg-sunken/60 px-3 py-2 " +
            "border-l-2 " +
            borderClass
          }
        >
          <Markdown>{safe}</Markdown>
        </div>
      </Section>
    )
  }

  if (!isMultiLine) {
    return (
      <Section>
        <blockquote
          className={
            "border-l-2 pl-3 font-sans text-sm leading-relaxed " +
            borderClass +
            " " +
            (isConversation ? "text-ink" : "italic text-ink-muted")
          }
        >
          {safe}
        </blockquote>
      </Section>
    )
  }
  return (
    <Section>
      <div
        className={
          "max-h-96 overflow-y-auto rounded-sm bg-sunken/60 px-3 py-2 " +
          "font-sans text-sm leading-relaxed whitespace-pre-wrap break-words " +
          "border-l-2 " +
          borderClass +
          " " +
          (isConversation ? "text-ink" : "italic text-ink-muted")
        }
      >
        {safe}
      </div>
    </Section>
  )
}

// ── Utilities ───────────────────────────────────────────────────────────────

function asString(v: unknown): string {
  return typeof v === "string" ? v : ""
}

function safeJsonStringify(v: unknown): string {
  if (v === undefined || v === null) return ""
  if (typeof v === "string") return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}
