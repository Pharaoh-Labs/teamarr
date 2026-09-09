import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/api/client"

const TOAST_ID = "cache-refresh"

export interface CacheRefreshStatus {
  in_progress: boolean
  status: "idle" | "starting" | "progress" | "complete" | "error"
  message: string
  percent: number
  phase: string
  provider: string
  current: number
  total: number
  error: string | null
  result: {
    leagues_count?: number
    teams_count?: number
  }
}

interface CacheRefreshContextValue {
  isRefreshing: boolean
  startRefresh: () => Promise<void>
}

const CacheRefreshContext = createContext<CacheRefreshContextValue | null>(null)

function ProgressDescription({ status }: { status: CacheRefreshStatus }) {
  return (
    <div className="mt-1 w-[356px] space-y-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${status.percent}%` }}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        {status.total > 0 ? `${status.current}/${status.total} leagues` : status.message}
      </div>
    </div>
  )
}

export function CacheRefreshProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<CacheRefreshStatus | null>(null)
  const wasRefreshing = useRef(false)
  const queryClient = useQueryClient()

  useEffect(() => {
    let mounted = true

    const poll = async () => {
      try {
        const next = await api.get<CacheRefreshStatus>("/cache/refresh/status")
        if (mounted) setStatus(next)
      } catch {
        // The application may not be available during its initial bootstrap.
      }
    }

    void poll()
    const interval = window.setInterval(() => void poll(), 500)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    if (!status) return

    if (status.in_progress) {
      wasRefreshing.current = true
      toast.loading(`Refreshing team/league cache (${status.percent}%)`, {
        id: TOAST_ID,
        duration: Infinity,
        description: <ProgressDescription status={status} />,
      })
      return
    }

    if (!wasRefreshing.current) return
    wasRefreshing.current = false
    queryClient.invalidateQueries({ queryKey: ["cacheStatus"] })

    if (status.status === "complete") {
      toast.success("Team/league cache refreshed", {
        id: TOAST_ID,
        duration: 5000,
        description: `Refreshed ${status.result.leagues_count ?? 0} leagues and ${status.result.teams_count ?? 0} teams`,
      })
    } else {
      toast.error("Team/league cache refresh failed", {
        id: TOAST_ID,
        duration: 8000,
        description: status.error || status.message,
      })
    }
  }, [queryClient, status])

  const startRefresh = async () => {
    const next = await api.post<CacheRefreshStatus>("/cache/refresh")
    setStatus(next)
  }

  return (
    <CacheRefreshContext.Provider value={{ isRefreshing: status?.in_progress ?? false, startRefresh }}>
      {children}
    </CacheRefreshContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCacheRefresh() {
  const context = useContext(CacheRefreshContext)
  if (!context) throw new Error("useCacheRefresh must be used within CacheRefreshProvider")
  return context
}
