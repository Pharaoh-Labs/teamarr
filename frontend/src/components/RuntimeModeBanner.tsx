import { useQuery } from "@tanstack/react-query"
import { FlaskConical, PauseCircle } from "lucide-react"

/**
 * Persistent banner for the #554 runtime flags. `SCHEDULER=off` and
 * `DRY_RUN=true` are env-only and silent by nature — "nothing is being
 * written" must never be something the operator has to discover.
 */
interface HealthRuntime {
  runtime?: { scheduler_enabled: boolean; dry_run: boolean }
}

export function RuntimeModeBanner() {
  const { data } = useQuery({
    queryKey: ["health", "runtime"],
    queryFn: async (): Promise<HealthRuntime> => {
      const r = await fetch("/health")
      return r.ok ? r.json() : {}
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })
  const runtime = data?.runtime
  if (!runtime) return null
  const schedulerOff = runtime.scheduler_enabled === false
  const dryRun = runtime.dry_run === true
  if (!schedulerOff && !dryRun) return null

  return (
    <div
      role="status"
      className="border-b border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-200 text-xs"
    >
      <div className="max-w-[1440px] mx-auto px-4 py-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
        {dryRun && (
          <span className="inline-flex items-center gap-1.5 font-medium">
            <FlaskConical className="h-3.5 w-3.5" />
            DRY RUN — outbound writes (Dispatcharr channels, media-server refreshes) are logged,
            not executed
          </span>
        )}
        {schedulerOff && (
          <span className="inline-flex items-center gap-1.5 font-medium">
            <PauseCircle className="h-3.5 w-3.5" />
            SCHEDULER OFF — nothing runs on a timer; manual generation still works
          </span>
        )}
      </div>
    </div>
  )
}
