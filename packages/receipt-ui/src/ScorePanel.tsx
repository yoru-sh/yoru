import type { SessionScore } from "./types"

// Session score panel — top of rail (above Red Flags).
//
// Rendering philosophy (SPACE paper § "expose axes, not composite"):
// surface the THREE axes explicitly; the composite/grade is headline but
// clicking-through shows the breakdown so auditors can see why.
//
// Visual: letter grade big (A/B/C/D/F), 3 horizontal bars (0-100) for
// Throughput / Reliability / Safety, each with its computed signal as a
// caption. No pie/donut — bars are the most honest for a 3-axis comp.

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

interface ScorePanelProps {
  score: SessionScore | null | undefined
}

// Color per grade — semantic (red = F, amber = D, accent = C/B, green-ish A)
// but constrained to the Swiss palette. Grade-A gets op-create (emerald),
// all others climb the accent ramp (amber).
const GRADE_COLOR: Record<string, { text: string; bg: string; ring: string }> = {
  A: { text: "text-op-create",   bg: "bg-op-create/15",   ring: "ring-op-create/50" },
  B: { text: "text-accent-500",  bg: "bg-accent-500/15",  ring: "ring-accent-500/50" },
  C: { text: "text-accent-500",  bg: "bg-accent-500/10",  ring: "ring-accent-500/30" },
  D: { text: "text-flag-shell-fg", bg: "bg-flag-shell-bg/50", ring: "ring-flag-shell/50" },
  F: { text: "text-flag-env-fg",   bg: "bg-flag-env-bg/60",   ring: "ring-flag-env/60" },
}

export function ScorePanel({ score }: ScorePanelProps) {
  if (!score) return null
  const color = GRADE_COLOR[score.grade] ?? GRADE_COLOR.C
  const breakdown = score.breakdown as Record<string, unknown>
  const tsr = typeof breakdown["tool_success_rate"] === "number"
    ? (breakdown["tool_success_rate"] as number)
    : null
  const errors = typeof breakdown["errors"] === "number"
    ? (breakdown["errors"] as number)
    : 0
  const uniqueTools = Array.isArray(breakdown["unique_tools"])
    ? (breakdown["unique_tools"] as string[]).length
    : 0
  const filesCount = typeof breakdown["files_count"] === "number"
    ? (breakdown["files_count"] as number)
    : 0
  const flagPenalty = typeof breakdown["flag_penalty"] === "number"
    ? (breakdown["flag_penalty"] as number)
    : 0
  const hardCeiling = breakdown["hard_ceiling"]

  return (
    <section aria-label="Session score" className="rounded-sm border border-rule bg-surface">
      <header className="flex items-baseline justify-between border-b border-dashed border-rule px-4 py-2">
        <h2 className={RUBRIC}>
          Score
          <span
            className="ml-1 normal-case text-ink-faint"
            title="Composite of three counterbalanced axes (DX Core 4 / SPACE methodology). Geometric mean — a zero on any axis tanks the overall. Hard cap applies on critical red flags."
          >
            ⓘ
          </span>
        </h2>
        <span className={`${RUBRIC} tabular-nums`}>{score.overall}/100</span>
      </header>

      {/* Grade + overall */}
      <div className="px-4 pt-3 pb-2 flex items-center gap-3">
        <div
          className={
            "inline-flex items-center justify-center rounded-sm border ring-1 ring-inset " +
            "w-12 h-12 font-mono text-2xl font-semibold tabular-nums " +
            color.text + " " + color.bg + " " + color.ring + " border-rule"
          }
          title={`Grade ${score.grade} — overall ${score.overall}/100`}
        >
          {score.grade}
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-sans text-sm text-ink-muted leading-relaxed">
            {gradeVerbal(score.grade)}
          </p>
          {hardCeiling !== null && hardCeiling !== undefined && (
            <p className="mt-0.5 font-mono text-micro text-flag-env-fg">
              capped at {String(hardCeiling)} due to critical flag
            </p>
          )}
        </div>
      </div>

      {/* Axes */}
      <div className="border-t border-dashed border-rule px-4 py-3 space-y-2">
        <AxisBar
          label="throughput"
          value={score.throughput}
          caption={`${filesCount} file${filesCount === 1 ? "" : "s"} · ${uniqueTools} tool${uniqueTools === 1 ? "" : "s"}`}
          title="Volume of shipped work: files changed, output tokens generated, tool diversity. Saturating normalization — 15 files / 300k output / 6 distinct tools = 100."
        />
        <AxisBar
          label="reliability"
          value={score.reliability}
          caption={
            tsr !== null
              ? `${tsr.toFixed(1)}% tool success · ${errors} error${errors === 1 ? "" : "s"}`
              : "no tool calls yet"
          }
          title="Tool Success Rate (arxiv 2510.18170) + absolute error penalty. A session with 50 errors out of 1000 calls (95% TSR) loses points vs. a 20-call session with zero errors."
        />
        <AxisBar
          label="safety"
          value={score.safety}
          caption={
            flagPenalty > 0
              ? `${flagPenalty} pt penalty from red flags`
              : "no red flags"
          }
          title="Severity-weighted red flag penalty. Worst: db_destructive (45), secret_aws (30). Not binary — a shell_rm matters less than a DROP TABLE, a pipe-to-shell matters more."
        />
      </div>
    </section>
  )
}

function AxisBar({
  label,
  value,
  caption,
  title,
}: {
  label: string
  value: number
  caption: string
  title: string
}) {
  const v = Math.max(0, Math.min(100, value))
  const barColor =
    v >= 70 ? "bg-op-create" : v >= 40 ? "bg-accent-500" : "bg-flag-env/80"
  return (
    <div title={title}>
      <div className="flex items-baseline justify-between font-mono text-micro">
        <span className="uppercase tracking-wider text-ink-faint">{label}</span>
        <span className="tabular-nums text-ink-muted">{value}</span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-sm bg-sunken" role="img" aria-label={`${label}: ${value} out of 100`}>
        <div className={`h-full ${barColor}`} style={{ width: `${v}%` }} />
      </div>
      {caption && (
        <p className="mt-0.5 font-mono text-micro text-ink-faint tabular-nums">
          {caption}
        </p>
      )}
    </div>
  )
}

function gradeVerbal(grade: string): string {
  switch (grade) {
    case "A": return "Excellent — shipped work with high reliability and no safety issues."
    case "B": return "Solid session — good across axes with minor friction."
    case "C": return "Acceptable — review weaker axis below for improvement."
    case "D": return "Weak session — look at reliability or safety specifically."
    case "F": return "Failed — critical issues present. Audit required."
    default: return ""
  }
}
