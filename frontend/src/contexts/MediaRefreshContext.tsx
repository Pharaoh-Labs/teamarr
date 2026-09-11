import { useEffect, useRef, type ReactNode } from "react"
import { toast } from "sonner"
import { api } from "@/api/client"

const TOAST_ID = "media-refresh"

interface MediaRefreshStatus {
  in_progress: boolean
  status: "idle" | "progress" | "complete" | "error"
  message: string
  current: number
  total: number
  error: string | null
  result: Array<{ server: string; success: boolean }>
}

function ProgressDescription({ status }: { status: MediaRefreshStatus }) {
  return (
    <div className="mt-1 w-[356px] space-y-1 text-xs text-muted-foreground">
      <div>{status.message}</div>
      {status.total > 1 && <div>{status.current}/{status.total} servers complete</div>}
    </div>
  )
}

export function MediaRefreshProvider({ children }: { children: ReactNode }) {
  const wasRefreshing = useRef(false)

  useEffect(() => {
    let mounted = true

    const poll = async () => {
      try {
        const status = await api.get<MediaRefreshStatus>("/epg/media-refresh/status")
        if (!mounted) return

        if (status.in_progress) {
          wasRefreshing.current = true
          toast.loading("Refreshing media servers", {
            id: TOAST_ID,
            duration: Infinity,
            description: <ProgressDescription status={status} />,
          })
        } else if (wasRefreshing.current) {
          wasRefreshing.current = false
          if (status.status === "complete") {
            const failed = status.result.filter((server) => !server.success).length
            toast[failed ? "warning" : "success"]("Media server refresh complete", {
              id: TOAST_ID,
              duration: failed ? 8000 : 5000,
              description: failed
                ? `${failed} server refresh failed`
                : `${status.result.length} server(s) refreshed`,
            })
          } else {
            toast.error("Media server refresh failed", {
              id: TOAST_ID,
              duration: 8000,
              description: status.error || status.message,
            })
          }
        }
      } catch {
        // The API is unavailable while the application starts or stops.
      }
    }

    void poll()
    const interval = window.setInterval(() => void poll(), 500)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  return children
}
