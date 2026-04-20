import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"

function updateParam(
  params: URLSearchParams,
  key: string,
  value: string | null,
): URLSearchParams {
  const next = new URLSearchParams(params)
  if (value === null || value === "") next.delete(key)
  else next.set(key, value)
  return next
}

const labelCls =
  "flex flex-col gap-1 font-mono text-micro uppercase tracking-wider text-ink-faint"
const inputCls =
  "h-8 rounded-sm border border-rule bg-surface px-2 " +
  "font-mono text-caption text-ink placeholder:text-ink-faint " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 " +
  "disabled:opacity-50"

export function FilterBar() {
  const [params, setParams] = useSearchParams()

  const userParam = params.get("user") ?? ""
  const fromParam = params.get("from") ?? ""
  const toParam = params.get("to") ?? ""
  const flagOnly = params.get("flag") === "1"
  const minCostParam = params.get("min_cost") ?? ""

  // Local mirror for the text input so we can debounce URL writes.
  const [userDraft, setUserDraft] = useState(userParam)
  useEffect(() => setUserDraft(userParam), [userParam])

  useEffect(() => {
    if (userDraft === userParam) return
    const t = setTimeout(() => {
      setParams(
        (prev) => updateParam(prev, "user", userDraft.trim() || null),
        { replace: true },
      )
    }, 300)
    return () => clearTimeout(t)
  }, [userDraft, userParam, setParams])

  const setOne = (key: string, value: string | null) => {
    setParams((prev) => updateParam(prev, key, value))
  }

  const clearAll = () => setParams(new URLSearchParams())

  const anyActive =
    !!userParam || !!fromParam || !!toParam || flagOnly || !!minCostParam

  return (
    <section
      aria-label="Filter sessions"
      className="flex flex-wrap items-end gap-4 rounded border border-rule bg-surface p-4"
    >
      <label className={labelCls}>
        <span>User</span>
        <input
          type="search"
          inputMode="email"
          value={userDraft}
          onChange={(e) => setUserDraft(e.target.value)}
          placeholder="alice@acme.dev"
          className={inputCls + " w-52"}
        />
      </label>

      <label className={labelCls}>
        <span>From</span>
        <input
          type="date"
          value={fromParam}
          onChange={(e) => setOne("from", e.target.value || null)}
          className={inputCls + " w-40"}
        />
      </label>

      <label className={labelCls}>
        <span>To</span>
        <input
          type="date"
          value={toParam}
          onChange={(e) => setOne("to", e.target.value || null)}
          className={inputCls + " w-40"}
        />
      </label>

      <label className={labelCls}>
        <span>Min cost ($)</span>
        <input
          type="number"
          min="0"
          step="0.5"
          value={minCostParam}
          onChange={(e) => setOne("min_cost", e.target.value || null)}
          placeholder="0.00"
          className={inputCls + " w-28"}
        />
      </label>

      <label className="flex items-center gap-2 font-mono text-caption text-ink-muted">
        <input
          type="checkbox"
          checked={flagOnly}
          onChange={(e) => setOne("flag", e.target.checked ? "1" : null)}
          className="h-4 w-4 cursor-pointer accent-accent-500"
        />
        <span>Flagged only</span>
      </label>

      <button
        type="button"
        onClick={clearAll}
        disabled={!anyActive}
        className={
          "ml-auto h-8 rounded-sm border border-rule px-3 " +
          "font-mono text-micro uppercase tracking-wider text-ink-muted " +
          "hover:bg-sunken disabled:cursor-not-allowed disabled:opacity-40 " +
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        }
      >
        Clear
      </button>
    </section>
  )
}
