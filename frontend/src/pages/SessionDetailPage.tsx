import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ApiError, getSession } from "../lib/api"
import type { SessionDetail } from "../types/receipt"
import { SessionHero } from "../features/sessions/SessionHero"
import { FileChangedRail } from "../features/sessions/FileChangedRail"
import { Timeline } from "../features/sessions/Timeline"

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const query = useQuery<SessionDetail>({
    queryKey: ["session", id],
    queryFn: () => getSession(id as string),
    enabled: Boolean(id),
  })

  if (!id) return <NotFound />

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-8">
      <nav className="font-mono text-micro uppercase tracking-wider text-ink-faint">
        <Link
          to="/"
          className="rounded-sm hover:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
        >
          ← All sessions
        </Link>
      </nav>

      {query.isPending && <LoadingState />}
      {query.isError && <ErrorState err={query.error} />}
      {query.data && <Receipt session={query.data} />}
    </div>
  )
}

function Receipt({ session }: { session: SessionDetail }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <main className="min-w-0 space-y-6">
        <SessionHero session={session} />
        <section
          aria-label="Timeline"
          className="rounded-sm border border-rule bg-surface"
        >
          <Timeline events={session.events ?? []} onFlagClick={noop} />
        </section>
      </main>
      <FileChangedRail session={session} />
    </div>
  )
}

function noop() {}

function LoadingState() {
  return (
    <div
      role="status"
      aria-label="Loading session"
      className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
    >
      <div className="space-y-6">
        <div className="space-y-2 rounded-sm border border-rule bg-surface p-4">
          <div aria-hidden className="h-4 w-1/2 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
          <div aria-hidden className="h-4 w-3/4 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
          <div aria-hidden className="h-4 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        </div>
        <div className="space-y-2 rounded-sm border border-rule bg-surface p-4">
          <div aria-hidden className="h-8 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
          <div aria-hidden className="h-8 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
          <div aria-hidden className="h-8 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        </div>
      </div>
      <div className="space-y-2 rounded-sm border border-rule bg-surface p-4">
        <div aria-hidden className="h-4 w-2/3 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        <div aria-hidden className="h-4 w-full rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
        <div aria-hidden className="h-4 w-1/2 rounded-sm bg-sunken/60 motion-safe:animate-pulse" />
      </div>
    </div>
  )
}

function ErrorState({ err }: { err: unknown }) {
  const status = err instanceof ApiError ? err.status : 0
  const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Unknown error"
  return (
    <div
      role="alert"
      className="rounded-sm border border-rule border-l-2 border-l-flag-env bg-surface px-4 py-3"
    >
      <p className="font-mono text-caption text-ink">
        <span className="mr-2 text-ink-muted">[{status || "ERR"}]</span>
        {msg}
      </p>
    </div>
  )
}

function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-6 py-12 text-center">
      <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">404</p>
      <h1 className="mt-2 font-sans text-2xl font-semibold text-ink">Session not found</h1>
      <Link
        to="/"
        className="mt-4 inline-block rounded-sm font-mono text-caption text-accent-500 underline-offset-2 hover:underline"
      >
        ← Home
      </Link>
    </div>
  )
}
