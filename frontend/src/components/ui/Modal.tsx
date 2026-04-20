import { useEffect, useId, useRef, type ReactNode } from "react"

export interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  closeOnOverlay?: boolean
  size?: "sm" | "md" | "lg" | "xl" | "2xl"
  children: ReactNode
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

const SIZE_CLASSES: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  "2xl": "max-w-2xl",
}

export function Modal({
  open,
  onClose,
  title,
  closeOnOverlay = true,
  size = "md",
  children,
}: ModalProps) {
  const cardRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== "Tab" || !cardRef.current) return
      const focusables = cardRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      if (focusables.length === 0) {
        e.preventDefault()
        return
      }
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement as HTMLElement | null
      if (e.shiftKey && active === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }

    window.addEventListener("keydown", onKey)
    const raf = requestAnimationFrame(() => {
      const focusables = cardRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      focusables?.[0]?.focus()
    })
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"

    return () => {
      window.removeEventListener("keydown", onKey)
      cancelAnimationFrame(raf)
      document.body.style.overflow = prevOverflow
      previouslyFocused?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        aria-hidden="true"
        onClick={closeOnOverlay ? onClose : undefined}
        className="absolute inset-0 bg-ink/40 backdrop-blur-sm animate-feed-in"
      />
      <div
        ref={cardRef}
        className={`relative z-10 w-full ${SIZE_CLASSES[size]} overflow-hidden rounded-sm border border-rule bg-surface shadow-lg animate-feed-in`}
      >
        <span id={titleId} className="sr-only">
          {title}
        </span>
        {children}
      </div>
    </div>
  )
}
