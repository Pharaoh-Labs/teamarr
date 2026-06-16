import { useState, useEffect } from "react"
import { Loader2 } from "lucide-react"
import { Alert } from "@/components/ui/alert"

interface StartupStatus {
  phase: string
  message: string
  is_ready: boolean
  elapsed_seconds: number
  error: string | null
}

interface HealthResponse {
  status: string
  version: string
  startup: StartupStatus
}

export function StartupOverlay() {
  const [status, setStatus] = useState<StartupStatus | null>(null)
  const [isReady, setIsReady] = useState(false)
  const [fadeOut, setFadeOut] = useState(false)

  useEffect(() => {
    let mounted = true
    let pollInterval: ReturnType<typeof setInterval> | null = null

    const checkHealth = async () => {
      try {
        const response = await fetch("/health")
        if (!response.ok) return

        const data: HealthResponse = await response.json()
        if (!mounted) return

        setStatus(data.startup)

        if (data.startup.is_ready) {
          // Start fade out animation
          setFadeOut(true)
          // Clear polling
          if (pollInterval) {
            clearInterval(pollInterval)
            pollInterval = null
          }
          // Remove overlay after animation
          setTimeout(() => {
            if (mounted) setIsReady(true)
          }, 500)
        }
      } catch {
        // Backend not available yet, keep polling
      }
    }

    // Initial check
    checkHealth()

    // Poll every 500ms until ready
    pollInterval = setInterval(checkHealth, 500)

    return () => {
      mounted = false
      if (pollInterval) clearInterval(pollInterval)
    }
  }, [])

  // Don't render anything once fully ready
  if (isReady) return null

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center bg-background transition-opacity duration-500 ${
        fadeOut ? "opacity-0" : "opacity-100"
      }`}
    >
      <div className="text-center space-y-4">
        {/* Logo/Title */}
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">Teamarr</h1>
          <p className="text-sm text-muted-foreground">Sports EPG Generator</p>
        </div>

        {/* Spinner */}
        <div className="flex justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>

        {/* Status Message */}
        <div className="space-y-1">
          <p className="text-sm font-medium">
            {status?.message || "Connecting..."}
          </p>
          {status && status.elapsed_seconds > 0 && (
            <p className="text-xs text-muted-foreground">
              {Math.round(status.elapsed_seconds)}s elapsed
            </p>
          )}
        </div>

        {/* Error State */}
        {status?.error && (
          <Alert variant="destructive" className="mt-4 max-w-sm">
            {status.error}
          </Alert>
        )}
      </div>
    </div>
  )
}
