import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { SessionHeroView, type SessionDetail } from "@receipt/ui"
import {
  exportSessionTrail,
  postSummary,
  revokeShareSession,
  shareSession,
} from "../../lib/api"
import { toast } from "../../components/Toaster"

interface SessionHeroProps {
  session: SessionDetail
}

// Marketing host that serves /s/<id> — mirrors backend env YORU_PUBLIC_URL.
// Kept client-side for display when a session is already public (the backend
// returns `is_public` on SessionDetail but doesn't include a URL on that
// shape; ShareResponse does).
const PUBLIC_SITE =
  (import.meta.env.VITE_PUBLIC_SITE_URL as string | undefined) ?? "https://yoru.sh"

// localStorage flag: first-time share confirm (#79 AC — one-time warning).
// Cleared by the user via devtools if they want to re-see the warning.
const SHARE_CONFIRM_KEY = "yoru.share.confirmed"

export function SessionHero({ session }: SessionHeroProps) {
  const [exporting, setExporting] = useState(false)
  const [sharing, setSharing] = useState(false)
  const queryClient = useQueryClient()

  async function onExport() {
    setExporting(true)
    try {
      await exportSessionTrail(session.id)
    } catch (err) {
      toast.error("Couldn't export trail", err instanceof Error ? err.message : String(err))
    } finally {
      setExporting(false)
    }
  }

  async function onToggleShare() {
    const currentlyPublic = Boolean(session.is_public)
    if (!currentlyPublic) {
      // First-time-only warning. Revoking doesn't prompt — it's already public,
      // the user is choosing to make it private again, which is a de-risking
      // action and doesn't need friction.
      const alreadyConfirmed =
        typeof window !== "undefined" &&
        window.localStorage?.getItem(SHARE_CONFIRM_KEY) === "1"
      if (!alreadyConfirmed) {
        const message = [
          "Make this session publicly shareable?",
          "",
          "Anyone with the link will see it at " + PUBLIC_SITE + "/s/" + session.id + ".",
          "",
          "Visible publicly: prompts, tool calls, file paths, red flags, grade.",
          "Always redacted: content of any event flagged secret_* (AWS / Stripe / JWT / SSH).",
          "",
          "You can revoke at any time from this same button.",
        ].join("\n")
        if (!window.confirm(message)) return
        try {
          window.localStorage?.setItem(SHARE_CONFIRM_KEY, "1")
        } catch {
          // quota / privacy-mode — no-op, user will see the prompt again next time
        }
      }
    }

    setSharing(true)
    try {
      const res = currentlyPublic
        ? await revokeShareSession(session.id)
        : await shareSession(session.id)
      if (res.public_url) {
        try {
          await navigator.clipboard.writeText(res.public_url)
          toast.success("Public URL copied to clipboard", res.public_url)
        } catch {
          toast.success("Session is now public", res.public_url)
        }
      } else {
        toast.success("Session is now private", "The public URL no longer resolves.")
      }
      // Refetch so session.is_public flips and the hero re-renders.
      await queryClient.invalidateQueries({ queryKey: ["session", session.id] })
    } catch (err) {
      toast.error(
        currentlyPublic ? "Couldn't revoke share" : "Couldn't make session public",
        err instanceof Error ? err.message : String(err),
      )
    } finally {
      setSharing(false)
    }
  }

  const summaryMutation = useMutation({
    mutationFn: () => postSummary(session.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", session.id] })
      queryClient.invalidateQueries({ queryKey: ["session", session.id, "summary"] })
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error("Couldn't generate summary", msg)
    },
  })

  const publicUrl = session.is_public ? `${PUBLIC_SITE}/s/${session.id}` : null

  return (
    <SessionHeroView
      session={session}
      onExport={onExport}
      isExporting={exporting}
      onGenerateSummary={() => summaryMutation.mutate()}
      isGeneratingSummary={summaryMutation.isPending}
      onToggleShare={onToggleShare}
      isSharing={sharing}
      publicShareUrl={publicUrl}
    />
  )
}
