import { useMemo, useState } from "react"
import type { SessionEvent, SessionDetail } from "./types"

// Token usage panel — reflects Anthropic's prompt-caching billing model.
//
// Key insight: `cache_read_input_tokens` is the same content being RE-READ
// across many API calls (Claude Code re-sends the whole conversation every
// turn). Summing them gives a huge number (~1B for a 3-day session) but that
// DOESN'T mean "1B unique tokens you typed" — it means "1B tokens billed as
// cache reads at 10% of input rate".
//
// The panel separates:
//   * UNIQUE WORK — output + cache_creation + fresh_input. What Claude
//     actually generated and what new content hit the model.
//   * RE-READS — cache_read_input_tokens. The same context re-loaded every
//     turn; dominates the raw input count but bills at 10% of input rate.
//
// Cost breakdown by billing dimension mirrors Anthropic's invoice: input /
// cache-write / cache-read / output. A "without cache" figure shows what
// the same session would cost if all cache_read tokens were billed as fresh
// input — the savings the cache provided.

const RUBRIC = "font-mono text-caption uppercase tracking-wider text-ink-faint"

// ── formatters ──────────────────────────────────────────────────────────────

function fmtTok(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`
  if (n < 1_000_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  return `${(n / 1_000_000_000).toFixed(2)}B`
}

function fmtCost(n: number): string {
  if (n === 0) return "$0"
  if (n < 0.01) return `$${n.toFixed(4)}`
  if (n < 1) return `$${n.toFixed(3)}`
  if (n < 100) return `$${n.toFixed(2)}`
  return `$${n.toFixed(0)}`
}

function pct(part: number, whole: number): number {
  if (!whole) return 0
  return Math.max(0, Math.min(1, part / whole))
}

// ── breakdown + effective rates ─────────────────────────────────────────────

interface Breakdown {
  freshIn: number
  cachedRead: number
  cacheWrite: number
  output: number
  totalIn: number
  cost: number
  callCount: number
  modelCounts: Map<string, number>
  // cost per dimension (derived)
  costFreshIn: number
  costCacheWrite: number
  costCacheRead: number
  costOutput: number
  // hypothetical cost if cache was disabled (all cache_read billed as fresh input)
  costNoCaching: number
}

// Effective per-token rates derived from the session's actual cost +
// token counts. Avoids hardcoding a price table on the frontend — we
// pick the dimension with the biggest delta and solve for its rate,
// then back-fill the others using the canonical Anthropic ratios
// (input=1×, cache_write=1.25×, cache_read=0.1×, output=5×).
// If the session cost is 0 (unpriced model) we fall back to $0.
function effectiveRates(b: Omit<Breakdown, "costFreshIn" | "costCacheWrite" | "costCacheRead" | "costOutput" | "costNoCaching">): {
  inRate: number
  cwRate: number
  crRate: number
  outRate: number
} {
  if (b.cost <= 0) return { inRate: 0, cwRate: 0, crRate: 0, outRate: 0 }
  // Solve: cost = fresh*IN + cw*1.25*IN + cr*0.1*IN + out*5*IN
  //      = IN * (fresh + cw*1.25 + cr*0.1 + out*5)
  const denom = b.freshIn + b.cacheWrite * 1.25 + b.cachedRead * 0.1 + b.output * 5
  const inRate = denom > 0 ? b.cost / denom : 0
  return {
    inRate,
    cwRate: inRate * 1.25,
    crRate: inRate * 0.1,
    outRate: inRate * 5,
  }
}

function computeBreakdown(usage: SessionEvent[], sessionCost: number): Breakdown {
  let freshIn = 0
  let cachedRead = 0
  let cacheWrite = 0
  let output = 0
  const modelCounts = new Map<string, number>()
  for (const e of usage) {
    const u = (e.tool_input ?? {}) as Record<string, number | string | undefined>
    freshIn += Number(u["input_tokens"] ?? 0)
    cachedRead += Number(u["cache_read_input_tokens"] ?? 0)
    cacheWrite += Number(u["cache_creation_input_tokens"] ?? 0)
    output += Number(u["output_tokens"] ?? e.tokens_output ?? 0)
    const model = (e.tool_name as string) ?? "unknown"
    modelCounts.set(model, (modelCounts.get(model) ?? 0) + 1)
  }
  const partial: Omit<Breakdown, "costFreshIn" | "costCacheWrite" | "costCacheRead" | "costOutput" | "costNoCaching"> = {
    freshIn, cachedRead, cacheWrite, output,
    totalIn: freshIn + cachedRead + cacheWrite,
    cost: sessionCost,
    callCount: usage.length,
    modelCounts,
  }
  const r = effectiveRates(partial)
  const costFreshIn = freshIn * r.inRate
  const costCacheWrite = cacheWrite * r.cwRate
  const costCacheRead = cachedRead * r.crRate
  const costOutput = output * r.outRate
  // "No caching" counterfactual: cache_read billed at fresh-input rate
  // (loses the 10× discount). cache_write would also vanish (new input).
  const costNoCaching =
    (freshIn + cachedRead + cacheWrite) * r.inRate + output * r.outRate
  return {
    ...partial,
    costFreshIn,
    costCacheWrite,
    costCacheRead,
    costOutput,
    costNoCaching,
  }
}

// ── panel ───────────────────────────────────────────────────────────────────

interface TokenPanelProps {
  session: SessionDetail
}

export function TokenPanel({ session }: TokenPanelProps) {
  const usage = session.usage_events ?? []
  const b = useMemo(() => computeBreakdown(usage, session.cost_usd ?? 0), [usage, session.cost_usd])
  const [showBreakdown, setShowBreakdown] = useState(false)

  if (b.totalIn === 0 && b.output === 0 && b.callCount === 0) return null

  // Unique work = generated content + new context written to cache + new
  // user input. Excludes cache reads (same content re-loaded N times).
  const uniqueWork = b.output + b.cacheWrite + b.freshIn
  const cacheEfficiency = pct(b.cachedRead, b.totalIn)
  const savings = Math.max(0, b.costNoCaching - b.cost)

  return (
    <section aria-label="Token usage" className="rounded-sm border border-rule bg-surface">
      <header className="flex items-baseline justify-between border-b border-dashed border-rule px-4 py-2">
        <h2 className={RUBRIC}>Token usage</h2>
        <span className={`${RUBRIC} tabular-nums`}>
          {b.callCount} call{b.callCount === 1 ? "" : "s"}
        </span>
      </header>

      {/* Hero — unique work, the "real" tokens processed. Cache reads are
          re-loads of the same content, counted separately below. */}
      <div className="px-4 pt-3 pb-2">
        <p className={`${RUBRIC} mb-1`}>
          unique work
          <span
            className="ml-1 normal-case text-ink-faint"
            title="Generated output + context written to cache + new user input. The actual content Claude processed, excluding cache re-reads of the same text."
          >
            ⓘ
          </span>
        </p>
        <p
          className="font-mono text-2xl font-semibold text-ink tabular-nums"
          title={`${uniqueWork.toLocaleString()} tokens`}
        >
          {fmtTok(uniqueWork)}
        </p>
        <p className="mt-0.5 font-mono text-micro tabular-nums text-ink-faint">
          {fmtTok(b.output)} output · {fmtTok(b.cacheWrite)} cache-write · {fmtTok(b.freshIn)} fresh
        </p>
      </div>

      {/* Cache efficiency */}
      <div className="border-t border-dashed border-rule px-4 py-3 space-y-2">
        <div className="flex items-baseline justify-between">
          <p className={RUBRIC}>
            cache efficiency
            <span
              className="ml-1 normal-case text-ink-faint"
              title="Share of input tokens served from Anthropic's prompt cache. Cache reads bill at 10% of fresh-input rate. High % means most context was re-used, keeping cost down."
            >
              ⓘ
            </span>
          </p>
          <p className="font-mono text-sm tabular-nums text-ink">
            {(cacheEfficiency * 100).toFixed(1)}%
          </p>
        </div>
        <EfficiencyBar cachePct={cacheEfficiency} />
        <p className="font-mono text-micro tabular-nums text-ink-faint">
          {fmtTok(b.cachedRead)} re-read · {fmtTok(b.totalIn)} total input
        </p>
      </div>

      {/* Cost breakdown by billing dimension */}
      <div className="border-t border-dashed border-rule px-4 py-3 space-y-2">
        <div className="flex items-baseline justify-between">
          <p className={RUBRIC}>
            api-equivalent cost
            <span
              className="ml-1 normal-case text-ink-faint"
              title="What this session would cost at Anthropic's per-token API rates. Claude Code subscription users pay a flat monthly fee — this $ is a value-consumed reference, not your wallet."
            >
              ⓘ
            </span>
          </p>
          <p className="font-mono text-sm font-semibold tabular-nums text-ink">
            {fmtCost(b.cost)}
          </p>
        </div>
        <CostBar breakdown={b} />
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-micro tabular-nums">
          <CostRow color="bg-accent-500" label="fresh in" value={fmtCost(b.costFreshIn)} />
          <CostRow color="bg-op-create" label="output" value={fmtCost(b.costOutput)} />
          <CostRow color="bg-ink-muted/70" label="cache-read" value={fmtCost(b.costCacheRead)} />
          <CostRow color="bg-ink-faint/70" label="cache-write" value={fmtCost(b.costCacheWrite)} />
        </dl>
        {savings > 0.01 && (
          <p className="mt-1 font-mono text-micro text-ink-muted">
            caching saved{" "}
            <span className="text-accent-500 tabular-nums">{fmtCost(savings)}</span>{" "}
            <span className="text-ink-faint">vs {fmtCost(b.costNoCaching)} uncached</span>
          </p>
        )}
      </div>

      {/* Per-call cost sparkline */}
      {b.callCount >= 3 && (
        <div className="border-t border-dashed border-rule px-4 py-3">
          <div className="mb-1 flex items-baseline justify-between">
            <p className={RUBRIC}>$/call trajectory</p>
            <p className="font-mono text-micro tabular-nums text-ink-faint">
              max {fmtCost(Math.max(...usage.map((e) => e.cost_usd ?? 0)))}
            </p>
          </div>
          <CallSparkline events={usage} />
        </div>
      )}

      {/* Model distribution */}
      {b.modelCounts.size > 1 && (
        <div className="border-t border-dashed border-rule px-4 py-2">
          <p className={`${RUBRIC} mb-1.5`}>models</p>
          <div className="flex flex-wrap gap-1">
            {[...b.modelCounts.entries()]
              .sort((a, b) => b[1] - a[1])
              .map(([model, count]) => (
                <span
                  key={model}
                  title={model}
                  className="inline-flex items-center gap-1 rounded-sm border border-rule px-1.5 py-0.5 font-mono text-micro tabular-nums"
                >
                  <span className="truncate max-w-[10rem] text-ink-muted">{model}</span>
                  <span className="text-ink-faint">{count}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Per-call breakdown (collapsible) */}
      {b.callCount > 0 && (
        <div className="border-t border-dashed border-rule">
          <button
            type="button"
            onClick={() => setShowBreakdown((v) => !v)}
            aria-expanded={showBreakdown}
            className={
              "flex w-full items-center justify-between px-4 py-2 font-mono text-micro uppercase tracking-wider " +
              "text-ink-faint hover:bg-sunken/40 " +
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
              "focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
            }
          >
            <span>per-call breakdown</span>
            <span aria-hidden>{showBreakdown ? "−" : "+"}</span>
          </button>
          {showBreakdown && (
            <div className="max-h-64 overflow-y-auto border-t border-dashed border-rule">
              <ol>
                {usage.map((e, i) => (
                  <UsageRow key={e.id} event={e} index={i + 1} />
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

// ── sub-components ──────────────────────────────────────────────────────────

function EfficiencyBar({ cachePct }: { cachePct: number }) {
  const fresh = (1 - cachePct) * 100
  const cached = cachePct * 100
  return (
    <div
      className="flex h-1.5 w-full overflow-hidden rounded-sm bg-sunken"
      role="img"
      aria-label={`${Math.round(cached)}% cache reads, ${Math.round(fresh)}% fresh input`}
    >
      <div className="h-full bg-ink-muted/70" style={{ width: `${cached}%` }} />
      <div className="h-full bg-accent-500" style={{ width: `${fresh}%` }} />
    </div>
  )
}

function CostBar({ breakdown }: { breakdown: Breakdown }) {
  const total = breakdown.cost || 1
  const fresh = (breakdown.costFreshIn / total) * 100
  const cw = (breakdown.costCacheWrite / total) * 100
  const cr = (breakdown.costCacheRead / total) * 100
  const out = (breakdown.costOutput / total) * 100
  return (
    <div
      className="flex h-1.5 w-full overflow-hidden rounded-sm bg-sunken"
      role="img"
      aria-label="Cost by billing dimension"
    >
      <div className="h-full bg-accent-500" style={{ width: `${fresh}%` }} title={`fresh in ${fresh.toFixed(1)}%`} />
      <div className="h-full bg-op-create" style={{ width: `${out}%` }} title={`output ${out.toFixed(1)}%`} />
      <div className="h-full bg-ink-muted/70" style={{ width: `${cr}%` }} title={`cache read ${cr.toFixed(1)}%`} />
      <div className="h-full bg-ink-faint/70" style={{ width: `${cw}%` }} title={`cache write ${cw.toFixed(1)}%`} />
    </div>
  )
}

function CostRow({
  color,
  label,
  value,
}: {
  color: string
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span aria-hidden className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${color}`} />
      <span className="shrink-0 text-ink-faint">{label}</span>
      <span className="ml-auto text-ink">{value}</span>
    </div>
  )
}

function CallSparkline({ events }: { events: SessionEvent[] }) {
  const costs = events.map((e) => e.cost_usd ?? 0)
  const max = Math.max(...costs, 0.0001)
  const width = 200
  const height = 28
  const n = costs.length
  if (n === 0) return null
  const points = costs.map((c, i) => {
    const x = n === 1 ? width / 2 : (i / (n - 1)) * (width - 2) + 1
    const y = (1 - c / max) * (height - 2) + 1
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-hidden="true"
      className="overflow-visible"
    >
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke="rgb(var(--accent-500))"
        strokeWidth={1}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

function UsageRow({ event, index }: { event: SessionEvent; index: number }) {
  const inTok = event.tokens_input ?? 0
  const outTok = event.tokens_output ?? 0
  const cost = event.cost_usd ?? 0
  const model = (event.tool_name as string) ?? "—"
  const u = (event.tool_input ?? {}) as Record<string, number | string | undefined>
  const cacheRead = Number(u["cache_read_input_tokens"] ?? 0)
  const cachePct = inTok > 0 ? (cacheRead / inTok) * 100 : 0
  return (
    <li className="border-b border-dashed border-rule last:border-b-0 px-4 py-1.5">
      <div className="flex items-baseline gap-2 font-mono text-micro">
        <span className="shrink-0 tabular-nums text-ink-faint">#{index}</span>
        <span className="min-w-0 flex-1 truncate text-ink-muted" title={model}>
          {model.replace(/^claude-/, "")}
        </span>
        {cachePct > 0 && (
          <span
            className="shrink-0 tabular-nums text-ink-faint"
            title={`${cacheRead.toLocaleString()} cache-read tokens`}
          >
            {cachePct.toFixed(0)}%c
          </span>
        )}
        <span className="shrink-0 tabular-nums text-ink-muted">
          {fmtTok(inTok)}→{fmtTok(outTok)}
        </span>
        <span className="shrink-0 tabular-nums text-accent-500">{fmtCost(cost)}</span>
      </div>
    </li>
  )
}
