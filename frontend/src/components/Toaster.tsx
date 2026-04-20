import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"

export type ToastKind = "info" | "success" | "error"

export interface Toast {
  id: string
  kind: ToastKind
  title: string
  detail?: string
}

export interface ToastAPI {
  info: (title: string, detail?: string) => void
  success: (title: string, detail?: string) => void
  error: (title: string, detail?: string) => void
}

const NOOP: ToastAPI = {
  info: () => {},
  success: () => {},
  error: () => {},
}

// Module-scoped singleton so non-React callers (src/lib/api.ts) can fire
// a toast without threading a hook through. ToasterProvider registers its
// live dispatch on mount; before mount or outside the tree this is a no-op.
let active: ToastAPI = NOOP
export const toast: ToastAPI = {
  info: (t, d) => active.info(t, d),
  success: (t, d) => active.success(t, d),
  error: (t, d) => active.error(t, d),
}

const ToastContext = createContext<ToastAPI>(NOOP)

export function useToast(): ToastAPI {
  return useContext(ToastContext)
}

const DISMISS_MS: Record<ToastKind, number> = {
  info: 4000,
  success: 4000,
  error: 8000,
}

export function ToasterProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const push = useCallback(
    (kind: ToastKind, title: string, detail?: string) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      setToasts((prev) => [{ id, kind, title, detail }, ...prev])
      const timer = setTimeout(() => dismiss(id), DISMISS_MS[kind])
      timersRef.current.set(id, timer)
    },
    [dismiss],
  )

  const api = useMemo<ToastAPI>(
    () => ({
      info: (t, d) => push("info", t, d),
      success: (t, d) => push("success", t, d),
      error: (t, d) => push("error", t, d),
    }),
    [push],
  )

  useEffect(() => {
    active = api
    return () => {
      active = NOOP
    }
  }, [api])

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((t) => clearTimeout(t))
      timers.clear()
    }
  }, [])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

const KIND_STYLES: Record<ToastKind, string> = {
  info: "border-accent-500",
  success: "border-accent-500",
  error: "border-flag-env",
}

const KIND_LABEL: Record<ToastKind, string> = {
  info: "INFO",
  success: "OK",
  error: "ERROR",
}

function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col-reverse gap-2"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  )
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const role = toast.kind === "error" ? "alert" : "status"
  return (
    <div
      role={role}
      className={
        "pointer-events-auto animate-feed-in rounded-sm border-l-2 bg-surface px-3 py-2 shadow-sm ring-1 ring-rule " +
        KIND_STYLES[toast.kind]
      }
    >
      <div className="flex items-start gap-2">
        <span className="font-mono text-micro font-semibold uppercase tracking-wider text-ink-muted">
          [{KIND_LABEL[toast.kind]}]
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-ink">{toast.title}</div>
          {toast.detail && (
            <div className="mt-0.5 break-words font-mono text-caption text-ink-muted">
              {toast.detail}
            </div>
          )}
        </div>
        {toast.kind === "error" && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss"
            className="-mr-1 -mt-1 rounded-sm px-1.5 py-0.5 text-ink-muted hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            ×
          </button>
        )}
      </div>
    </div>
  )
}
