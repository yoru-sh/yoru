import { useMemo } from "react"
import type { SessionEvent } from "../../types/receipt"

// Inline SVG sparkline — cumulative cost over the ordered events list.
// Zero dependency, ~40 LOC. Swiss: single accent line, no axes, no gradient.
// Fills with a semi-transparent area under the line for body; final tick
// gets a small anchor circle so the eye lands on "where we ended up".

interface CostSparklineProps {
  events: SessionEvent[]
  /** Total cost (from session.cost_usd) — shown as label to the right. */
  totalUsd: number
  width?: number
  height?: number
  className?: string
}

export function CostSparkline({
  events,
  totalUsd,
  width = 120,
  height = 24,
  className = "",
}: CostSparklineProps) {
  const { path, area, lastPoint, hasData } = useMemo(() => {
    const points: Array<{ x: number; y: number; cum: number }> = []
    let cum = 0
    const seq = events.filter((e) => typeof e.cost_usd === "number")
    if (seq.length === 0) return { path: "", area: "", lastPoint: null, hasData: false }
    seq.forEach((e) => {
      cum += e.cost_usd ?? 0
      points.push({ x: 0, y: 0, cum })
    })
    const max = points[points.length - 1].cum || 1
    const n = points.length
    // Horizontal spread; leave 1px margin so stroke isn't clipped.
    points.forEach((p, i) => {
      p.x = n === 1 ? width / 2 : (i / (n - 1)) * (width - 2) + 1
      // Invert Y: higher cost = lower y in SVG.
      p.y = max === 0 ? height - 1 : (1 - p.cum / max) * (height - 2) + 1
    })
    const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ")
    const areaD =
      `M${points[0].x.toFixed(1)} ${(height - 1).toFixed(1)} ` +
      points.map((p) => `L${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") +
      ` L${points[points.length - 1].x.toFixed(1)} ${(height - 1).toFixed(1)} Z`
    return { path: d, area: areaD, lastPoint: points[points.length - 1], hasData: true }
  }, [events, width, height])

  if (!hasData) {
    return (
      <span className={"font-mono text-caption text-ink-faint tabular-nums " + className}>
        ${totalUsd.toFixed(2)}
      </span>
    )
  }

  return (
    <div
      className={"inline-flex items-center gap-2 " + className}
      aria-label={`Cumulative cost sparkline · total $${totalUsd.toFixed(4)}`}
    >
      <svg
        width={width}
        height={height}
        role="img"
        aria-hidden="true"
        className="shrink-0 overflow-visible"
      >
        <path d={area} fill="rgb(var(--accent-500) / 0.12)" />
        <path
          d={path}
          fill="none"
          stroke="rgb(var(--accent-500))"
          strokeWidth={1}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {lastPoint && (
          <circle
            cx={lastPoint.x}
            cy={lastPoint.y}
            r={2}
            fill="rgb(var(--accent-500))"
          />
        )}
      </svg>
      <span className="font-mono text-sm text-ink tabular-nums">
        ${totalUsd.toFixed(4)}
      </span>
    </div>
  )
}
