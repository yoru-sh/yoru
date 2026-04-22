import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { SessionHeroView, type SessionDetail } from "@receipt/ui"
import { exportSessionTrail, postSummary } from "../../lib/api"
import { toast } from "../../components/Toaster"

interface SessionHeroProps {
  session: SessionDetail
}

export function SessionHero({ session }: SessionHeroProps) {
  const [exporting, setExporting] = useState(false)
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

  return (
    <SessionHeroView
      session={session}
      onExport={onExport}
      isExporting={exporting}
      onGenerateSummary={() => summaryMutation.mutate()}
      isGeneratingSummary={summaryMutation.isPending}
    />
  )
}
