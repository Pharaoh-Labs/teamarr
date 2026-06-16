import { useState } from "react"
import { toast } from "sonner"
import { CheckCircle, XCircle, AlertTriangle, Clock, Tv, Target, Copy, Check, Loader2 } from "lucide-react"
import { useDispatcharrStatus } from "@/hooks/useSettings"
import { useMatchRate, matchRateColor } from "@/hooks/useMatchRate"
import { useDateFormat } from "@/hooks/useDateFormat"
import { useGenerationProgress } from "@/contexts/GenerationContext"
import { getTeamXmltvUrl } from "@/api/epg"
import type { ProcessingRun } from "@/api/epg"

const DAY_MS = 24 * 60 * 60 * 1000

function formatDuration(ms: number | null | undefined): string | null {
  if (!ms) return null
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}

/**
 * Read-only health strip for the Dashboard (epic 7rfd). Answers "is my system
 * healthy?" at a glance: Dispatcharr connection, last generation (status +
 * relative time + duration, color-coded by staleness), live channel count, and
 * a copy button for the XMLTV URL. No chip navigation — the lone control is the
 * URL copy.
 */
export function StatusStrip({ lastRun }: { lastRun?: ProcessingRun }) {
  const dispatcharr = useDispatcharrStatus()
  const matchRate = useMatchRate()
  const { formatRelativeTime } = useDateFormat()
  const { isGenerating } = useGenerationProgress()
  const [copied, setCopied] = useState(false)

  // While a run is active these three values are mid-recompute — show a spinner
  // in their place until the run finishes and the fresh numbers land.
  const Spinner = () => <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />

  const epgUrl = `${window.location.origin}${getTeamXmltvUrl()}`

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(epgUrl)
      } else {
        const ta = document.createElement("textarea")
        ta.value = epgUrl
        ta.style.position = "fixed"
        ta.style.opacity = "0"
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        document.execCommand("copy")
        document.body.removeChild(ta)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      toast.success("EPG URL copied")
    } catch {
      toast.error("Failed to copy URL")
    }
  }

  // --- Dispatcharr connection chip ---
  const d = dispatcharr.data
  let dDot = "bg-muted-foreground/40"
  let dLabel = "Not configured"
  let dTitle: string | undefined
  if (d?.connected) {
    dDot = "bg-green-500"
    dLabel = "Connected"
  } else if (d?.configured && d?.error) {
    dDot = "bg-red-500"
    dLabel = "Error"
    dTitle = d.error
  } else if (d?.configured) {
    dDot = "bg-amber-500"
    dLabel = "Disconnected"
  }

  // --- Last generated chip ---
  const finishedAt = lastRun?.completed_at ?? lastRun?.started_at ?? null
  const ageMs = finishedAt ? Date.now() - new Date(finishedAt).getTime() : null
  const failed = lastRun ? lastRun.status === "failed" || lastRun.status === "cancelled" : false

  // Color: red if never/failed or >3 days; amber 1–3 days; green <1 day.
  let genColor = "text-muted-foreground"
  let GenIcon = Clock
  if (!lastRun) {
    GenIcon = Clock
  } else if (failed) {
    genColor = "text-red-500"
    GenIcon = XCircle
  } else if (ageMs != null && ageMs > 3 * DAY_MS) {
    genColor = "text-red-500"
    GenIcon = AlertTriangle
  } else if (ageMs != null && ageMs > DAY_MS) {
    genColor = "text-amber-500"
    GenIcon = AlertTriangle
  } else {
    genColor = "text-green-600"
    GenIcon = CheckCircle
  }

  const genWhen = finishedAt ? formatRelativeTime(finishedAt) : "Never generated"
  const genDuration = formatDuration(lastRun?.duration_ms)
  const liveChannels = lastRun?.channels?.active

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border bg-muted/30 px-4 py-2.5 text-sm">
      {/* Dispatcharr */}
      <div className="flex items-center gap-2" title={dTitle}>
        <span className={`inline-block h-2 w-2 rounded-full ${dDot}`} />
        <span className="text-muted-foreground">Dispatcharr</span>
        <span className="font-medium">{dLabel}</span>
      </div>

      <span className="hidden h-4 w-px bg-border sm:inline-block" />

      {/* Last generated */}
      <div className="flex items-center gap-2">
        {isGenerating ? (
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        ) : (
          <GenIcon className={`h-4 w-4 ${genColor}`} />
        )}
        <span className="text-muted-foreground">Last generated</span>
        {isGenerating ? (
          <span className="font-medium text-muted-foreground">Generating…</span>
        ) : (
          <>
            <span className="font-medium">{genWhen}</span>
            {genDuration && !failed && (
              <span className="text-xs text-muted-foreground">({genDuration})</span>
            )}
          </>
        )}
      </div>

      <span className="hidden h-4 w-px bg-border sm:inline-block" />

      {/* Live channels */}
      <div className="flex items-center gap-2">
        <Tv className="h-4 w-4 text-muted-foreground" />
        {isGenerating ? <Spinner /> : <span className="font-medium">{liveChannels ?? "—"}</span>}
        <span className="text-muted-foreground">managed channels</span>
      </div>

      {(matchRate.hasData || isGenerating) && (
        <>
          <span className="hidden h-4 w-px bg-border sm:inline-block" />
          <div className="flex items-center gap-2">
            <Target className={`h-4 w-4 ${isGenerating ? "text-muted-foreground" : matchRateColor(matchRate.rate)}`} />
            {isGenerating ? (
              <Spinner />
            ) : (
              <span className={`font-medium ${matchRateColor(matchRate.rate)}`}>{matchRate.rate}%</span>
            )}
            <span className="text-muted-foreground">matched</span>
          </div>
        </>
      )}

      {/* XMLTV URL + copy — pushed to the right */}
      <div className="ml-auto flex min-w-0 items-center gap-2">
        <span className="shrink-0 text-muted-foreground">EPG URL</span>
        <code
          className="min-w-0 max-w-[22rem] truncate rounded bg-background px-2 py-1 font-mono text-xs text-muted-foreground"
          title={epgUrl}
        >
          {epgUrl}
        </code>
        <button
          onClick={handleCopy}
          title="Copy EPG URL"
          className="inline-flex shrink-0 items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  )
}
