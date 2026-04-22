import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { apiFetch } from "../lib/api"

type State =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success"; code: string }
  | { kind: "error"; message: string }

function formatCode(raw: string): string {
  const clean = raw.toUpperCase().replace(/[^A-Z0-9]/g, "")
  if (clean.length <= 4) return clean
  return `${clean.slice(0, 4)}-${clean.slice(4, 8)}`
}

export function PairCliPage() {
  const [params] = useSearchParams()
  const initialCode = useMemo(() => formatCode(params.get("code") ?? ""), [params])
  const [code, setCode] = useState(initialCode)
  const [state, setState] = useState<State>({ kind: "idle" })

  useEffect(() => {
    setCode(initialCode)
  }, [initialCode])

  const canSubmit = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code) && state.kind !== "submitting"

  async function authorize(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setState({ kind: "submitting" })
    try {
      await apiFetch<void>("/auth/device-code/approve", {
        method: "POST",
        body: JSON.stringify({ user_code: code }),
      })
      setState({ kind: "success", code })
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not authorize"
      setState({ kind: "error", message: msg })
    }
  }

  return (
    <div className="mx-auto w-full max-w-xl px-6 py-16">
      <header className="mb-8">
        <p className="font-mono text-micro uppercase tracking-wider text-ink-muted">
          Receipt CLI
        </p>
        <h1 className="mt-2 font-serif text-h2 text-ink">Pair a new device</h1>
        <p className="mt-2 text-sm text-ink-muted">
          You ran{" "}
          <code className="rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-caption">
            receipt init
          </code>{" "}
          on a machine. Confirm the code it printed to pair that machine with your
          account.
        </p>
      </header>

      {state.kind === "success" ? (
        <div
          role="status"
          className="rounded border border-flag-none/40 bg-flag-none/5 p-6"
        >
          <p className="font-mono text-micro uppercase tracking-wider text-flag-none">
            Paired
          </p>
          <h2 className="mt-2 font-serif text-h3 text-ink">Device authorized</h2>
          <p className="mt-3 text-sm text-ink">
            Your CLI will finish setup in a few seconds. You can close this tab.
          </p>
          <p className="mt-2 text-caption text-ink-muted">
            Code <code className="font-mono text-ink">{state.code}</code> has been
            consumed and is no longer valid.
          </p>
        </div>
      ) : (
        <form onSubmit={authorize} className="space-y-5">
          <div>
            <label
              htmlFor="pair-code"
              className="block font-mono text-micro uppercase tracking-wider text-ink-muted"
            >
              Pairing code
            </label>
            <input
              id="pair-code"
              autoFocus
              autoComplete="one-time-code"
              inputMode="text"
              spellCheck={false}
              value={code}
              onChange={(e) => setCode(formatCode(e.target.value))}
              placeholder="ABCD-EFGH"
              maxLength={9}
              className="mt-2 w-full rounded border border-rule bg-canvas px-4 py-3 text-center font-mono text-h3 tracking-[0.3em] text-ink outline-none focus:border-ink"
              aria-describedby="pair-hint"
            />
            <p id="pair-hint" className="mt-2 text-caption text-ink-muted">
              Match this exactly with the code printed by your terminal.
            </p>
          </div>

          {state.kind === "error" && (
            <p role="alert" className="text-sm text-flag-secret">
              {state.message}
            </p>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full rounded border border-ink bg-ink py-3 font-mono text-sm uppercase tracking-wider text-canvas transition hover:bg-ink-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            {state.kind === "submitting" ? "Authorizing…" : "Authorize this device"}
          </button>

          <p className="text-caption text-ink-muted">
            Only authorize codes you generated yourself. A valid code grants the
            machine permission to stream events to your account until you revoke
            it from{" "}
            <a
              href="/settings/profile"
              className="underline decoration-rule underline-offset-2 hover:text-ink"
            >
              Settings → Tokens
            </a>
            .
          </p>
        </form>
      )}
    </div>
  )
}
