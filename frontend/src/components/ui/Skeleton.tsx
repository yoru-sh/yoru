import clsx from "clsx"

const BASE = "motion-safe:animate-pulse bg-sunken/60"

interface Props {
  className?: string
  decorative?: boolean
}

function ariaProps(decorative?: boolean) {
  return decorative
    ? ({ "aria-hidden": true } as const)
    : ({ role: "status" as const, "aria-label": "Loading…" })
}

function Line({ className, decorative }: Props) {
  return (
    <div
      {...ariaProps(decorative)}
      className={clsx(BASE, "h-4 w-full rounded-sm", className)}
    />
  )
}

function ListRow({ className, decorative }: Props) {
  return (
    <div
      {...ariaProps(decorative)}
      className={clsx(BASE, "h-10 w-full rounded-sm", className)}
    />
  )
}

function Avatar({ className, decorative }: Props) {
  return (
    <div
      {...ariaProps(decorative)}
      className={clsx(BASE, "h-8 w-8 rounded-full", className)}
    />
  )
}

function Card({ className, decorative }: Props) {
  return (
    <div
      {...ariaProps(decorative)}
      className={clsx("rounded border border-rule bg-surface p-4", className)}
    >
      <div className="space-y-2">
        <Line decorative className="w-11/12" />
        <Line decorative className="w-10/12" />
        <Line decorative className="w-8/12" />
      </div>
    </div>
  )
}

export const Skeleton = { Line, Card, ListRow, Avatar }
