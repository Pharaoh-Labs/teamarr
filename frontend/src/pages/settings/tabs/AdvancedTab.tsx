import { toast } from "sonner"
import { Loader2, Database, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScheduledChannelResetCard } from "@/components/ScheduledChannelResetCard"
import {
  useCacheStatus,
  useRefreshCache,
  useGameDataCacheStats,
  useClearGameDataCache,
  useClearAllRuns,
  useMatchCacheStats,
  useClearAllMatchCache,
} from "@/hooks/useEPG"
import { BackupRestoreCard } from "../BackupRestoreCard"
import { formatRelativeTime } from "../format"

function DataCachesCard() {
  const { data: cacheStatus, refetch: refetchCache } = useCacheStatus()
  const refreshCacheMutation = useRefreshCache()
  const { data: gameDataCacheStats } = useGameDataCacheStats()
  const clearGameDataCacheMutation = useClearGameDataCache()
  const clearAllRunsMutation = useClearAllRuns()
  const { data: matchCacheStats } = useMatchCacheStats()
  const clearAllMatchCacheMutation = useClearAllMatchCache()

  const handleRefreshCache = async () => {
    try {
      const result = await refreshCacheMutation.mutateAsync()
      toast.success(result.message)
      refetchCache()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start cache refresh")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Data Caches
            </CardTitle>
          </div>
          {cacheStatus?.is_stale && (
            <Badge variant="warning">Directory Stale</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 lg:divide-x">
          {/* Team & League Directory Section */}
          <div className="flex flex-col gap-4 lg:pr-6">
            <h4 className="text-sm font-medium text-center">Team & League Directory</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="text-center">
                <div className="text-2xl font-bold">{cacheStatus?.leagues_count ?? 0}</div>
                <div className="text-xs text-muted-foreground">Leagues</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">{cacheStatus?.teams_count ?? 0}</div>
                <div className="text-xs text-muted-foreground">Teams</div>
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              {formatRelativeTime(cacheStatus?.last_refresh ?? null)}
              {cacheStatus?.refresh_duration_seconds && ` (${cacheStatus.refresh_duration_seconds.toFixed(1)}s)`}
            </div>

            {cacheStatus?.is_empty && (
              <div className="text-center py-2 text-muted-foreground text-xs">
                Empty. Refresh to populate.
              </div>
            )}

            {cacheStatus?.last_error && (
              <div className="text-xs text-destructive">
                Error: {cacheStatus.last_error}
              </div>
            )}

            <Button
              onClick={handleRefreshCache}
              disabled={refreshCacheMutation.isPending || cacheStatus?.refresh_in_progress}
              className="w-full mt-auto"
              size="sm"
            >
              {(refreshCacheMutation.isPending || cacheStatus?.refresh_in_progress) && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              {cacheStatus?.refresh_in_progress ? "Refreshing..." : "Refresh Directory"}
            </Button>
          </div>

          {/* Game Data Cache Section */}
          <div className="flex flex-col gap-4 lg:pl-6">
            <h4 className="text-sm font-medium text-center">Game Data Cache</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="text-center">
                <div className="text-2xl font-bold">{gameDataCacheStats?.active_entries ?? 0}</div>
                <div className="text-xs text-muted-foreground">Active Entries</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">{gameDataCacheStats?.pending_writes ?? 0}</div>
                <div className="text-xs text-muted-foreground">Pending Writes</div>
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              Schedules, scores, and odds
            </div>

            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                clearGameDataCacheMutation.mutate(undefined, {
                  onSuccess: (data) => toast.success(data.message),
                  onError: () => toast.error("Failed to clear game data cache"),
                })
              }}
              disabled={clearGameDataCacheMutation.isPending}
              className="w-full mt-auto"
            >
              {clearGameDataCacheMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Clear Game Cache
            </Button>
          </div>

          {/* Stream Match Cache Section */}
          <div className="flex flex-col gap-4 lg:pl-6">
            <h4 className="text-sm font-medium text-center">Stream Match Cache</h4>
            <div className="text-center">
              <div className="text-2xl font-bold">{matchCacheStats?.total_entries ?? 0}</div>
              <div className="text-xs text-muted-foreground">Cached Matches</div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              Stream-to-event fingerprint matches
            </div>

            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                clearAllMatchCacheMutation.mutate(undefined, {
                  onSuccess: (data) => toast.success(`Cleared ${data.total_cleared ?? 0} match cache entries`),
                  onError: () => toast.error("Failed to clear match cache"),
                })
              }}
              disabled={clearAllMatchCacheMutation.isPending}
              className="w-full mt-auto"
            >
              {clearAllMatchCacheMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Clear Match Cache
            </Button>
          </div>

          {/* Run History Cleanup Section */}
          <div className="flex flex-col gap-4 lg:pl-6">
            <h4 className="text-sm font-medium text-center">Run History</h4>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">
                Processing run logs and statistics
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              Auto-cleaned to 30 days after each run
            </div>

            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                clearAllRunsMutation.mutate(undefined, {
                  onSuccess: (data) => toast.success(data.message),
                  onError: () => toast.error("Failed to clear run history"),
                })
              }}
              disabled={clearAllRunsMutation.isPending}
              className="w-full mt-auto"
            >
              {clearAllRunsMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Clear Run History
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function AdvancedTab() {
  return (
    <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Advanced</h2>
      </div>

      <BackupRestoreCard />
      <ScheduledChannelResetCard />
      <DataCachesCard />
    </>
  )
}
