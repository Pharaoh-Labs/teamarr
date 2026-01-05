import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from "react"
import { toast } from "sonner"

interface GenerationStatus {
  in_progress: boolean
  status: string
  message: string
  percent: number
  phase: string
  current: number
  total: number
  item_name: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  result: {
    success?: boolean
    programmes_count?: number
    teams_processed?: number
    groups_processed?: number
    duration_seconds?: number
    run_id?: number
  }
}

interface GenerationContextValue {
  startGeneration: (onComplete?: (result: GenerationStatus["result"]) => void) => void
  isGenerating: boolean
}

const GenerationContext = createContext<GenerationContextValue | null>(null)

const TOAST_ID = "epg-generation"

// Progress description component for toast
function ProgressDescription({ status }: { status: GenerationStatus | null }) {
  const percent = status?.percent ?? 0
  const itemName = status?.item_name
  const current = status?.current ?? 0
  const total = status?.total ?? 0

  // Check if this is stream-level progress (contains ✓ or ✗)
  const isStreamProgress = itemName && (itemName.includes("✓") || itemName.includes("✗"))

  return (
    <div className="space-y-2 mt-1 w-full max-w-[414px]">
      {/* Progress bar */}
      <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
      {/* Current item - wrap text naturally */}
      {itemName && (
        <div className="text-xs text-muted-foreground break-words">
          {isStreamProgress ? (
            <>{itemName} — {percent}%</>
          ) : (
            <>{itemName}{total > 0 && ` (${current}/${total})`} — {percent}%</>
          )}
        </div>
      )}
    </div>
  )
}

function getPhaseLabel(status: GenerationStatus | null): string {
  if (!status) return "Starting..."
  switch (status.phase) {
    case "teams":
      return "Processing Teams"
    case "groups":
      return "Processing Event Groups"
    case "saving":
      return "Saving XMLTV"
    case "dispatcharr":
      return "Syncing with Dispatcharr"
    case "lifecycle":
      return "Processing Channels"
    case "reconciliation":
      return "Running Reconciliation"
    case "cleanup":
      return "Cleaning Up"
    case "complete":
      return "Complete"
    default:
      return status.message || "Processing..."
  }
}

export function GenerationProvider({ children }: { children: ReactNode }) {
  const [isGenerating, setIsGenerating] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const onCompleteRef = useRef<((result: GenerationStatus["result"]) => void) | null>(null)
  const pollIntervalRef = useRef<number | null>(null)

  // Check for in-progress generation on mount
  useEffect(() => {
    fetch("/api/v1/epg/generate/status")
      .then((res) => res.json())
      .then((data: GenerationStatus) => {
        if (data.in_progress) {
          // Generation is in progress, reconnect
          setIsGenerating(true)
          reconnectToGeneration()
        }
      })
      .catch(console.error)

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  const updateToast = useCallback((status: GenerationStatus | null, isStarting: boolean = false) => {
    const title = isStarting ? "Starting EPG generation..." : getPhaseLabel(status)

    // Use standard toast.loading with description containing progress bar
    toast.loading(title, {
      id: TOAST_ID,
      duration: Infinity,
      description: status ? <ProgressDescription status={status} /> : undefined,
    })
  }, [])

  const handleComplete = useCallback((data: GenerationStatus) => {
    setIsGenerating(false)

    // Convert to success or error toast
    if (data.status === "complete") {
      const result = data.result
      toast.success("EPG Generated", {
        id: TOAST_ID,
        description: `${result.programmes_count} programmes in ${result.duration_seconds}s`,
        duration: 5000,
      })
    } else {
      toast.error("Generation Failed", {
        id: TOAST_ID,
        description: data.error || "Unknown error",
        duration: 8000,
      })
    }

    if (data.status === "complete" && onCompleteRef.current) {
      onCompleteRef.current(data.result)
      onCompleteRef.current = null
    }
  }, [])

  const reconnectToGeneration = useCallback(() => {
    // Use polling instead of SSE for reconnection (more reliable)
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
    }

    const poll = () => {
      fetch("/api/v1/epg/generate/status")
        .then((res) => res.json())
        .then((data: GenerationStatus) => {
          updateToast(data)

          if (data.status === "complete" || data.status === "error") {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current)
              pollIntervalRef.current = null
            }
            handleComplete(data)
          }
        })
        .catch(console.error)
    }

    // Poll immediately and then every 500ms
    poll()
    pollIntervalRef.current = window.setInterval(poll, 500)
  }, [updateToast, handleComplete])

  const startGeneration = useCallback((onComplete?: (result: GenerationStatus["result"]) => void) => {
    if (isGenerating) {
      toast.error("Generation already in progress")
      return
    }

    setIsGenerating(true)
    onCompleteRef.current = onComplete || null

    // Create initial toast
    updateToast(null as unknown as GenerationStatus, true)

    // Start SSE connection
    const eventSource = new EventSource("/api/v1/epg/generate/stream")
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as GenerationStatus
        updateToast(data)

        if (data.status === "complete" || data.status === "error") {
          eventSource.close()
          eventSourceRef.current = null
          handleComplete(data)
        }
      } catch (e) {
        console.error("Failed to parse SSE data:", e)
      }
    }

    eventSource.onerror = () => {
      eventSource.close()
      eventSourceRef.current = null

      // Fall back to polling
      reconnectToGeneration()
    }
  }, [isGenerating, updateToast, handleComplete, reconnectToGeneration])

  return (
    <GenerationContext.Provider value={{ startGeneration, isGenerating }}>
      {children}
    </GenerationContext.Provider>
  )
}

export function useGenerationProgress() {
  const context = useContext(GenerationContext)
  if (!context) {
    throw new Error("useGenerationProgress must be used within a GenerationProvider")
  }
  return context
}
