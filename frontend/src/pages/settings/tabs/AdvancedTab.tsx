import { useEffect, useState } from "react"
import { toast } from "sonner"
import { LoaderCircle, Database, HardDrive, ScrollText, Shrink, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { SaveButton } from "@/components/ui/save-button"
import { api } from "@/api/client"
import { ScheduledChannelResetCard } from "@/components/ScheduledChannelResetCard"
import {
  useCacheStatus,
  useGameDataCacheStats,
  useClearGameDataCache,
  useClearAllRuns,
  useMatchCacheStats,
  useClearAllMatchCache,
  useDatabaseStatus,
  useCompactDatabase,
} from "@/hooks/useEPG"
import { useReconciliationSettings, useUpdateReconciliationSettings } from "@/hooks/useSettings"
import { useCacheRefresh } from "@/contexts/CacheRefreshContext"
import { GracenoteOverridesCard } from "@/components/GracenoteOverridesCard"
import { BackupRestoreCard } from "../BackupRestoreCard"
import { formatBytes, formatRelativeTime } from "../format"

interface LogLevelState {
  level: string
  default: string
  levels: string[]
}

function LogLevelCard() {
  const [state, setState] = useState<LogLevelState | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .get<LogLevelState>("/logging/level")
      .then(setState)
      .catch(() => setState(null))
  }, [])

  const handleChange = async (level: string) => {
    setSaving(true)
    try {
      const next = await api.put<LogLevelState>("/logging/level", { level })
      setState(next)
      toast.success(`Console log level set to ${next.level} (until restart)`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to set log level")
    } finally {
      setSaving(false)
    }
  }

  if (!state) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ScrollText className="h-5 w-5" />
          Logging
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          <Label htmlFor="console-log-level">Console log level</Label>
          <Select
            id="console-log-level"
            value={state.level}
            onChange={(e) => handleChange(e.target.value)}
            disabled={saving}
          >
            {state.levels.map((level) => (
              <option key={level} value={level}>
                {level}
                {level === state.default ? " (default)" : ""}
              </option>
            ))}
          </Select>
          <p className="text-sm text-muted-foreground">
            Applies immediately, no restart. Temporary: a restart returns to the{" "}
            <code>LOG_LEVEL</code> default ({state.default}). The log file always
            captures DEBUG regardless.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

function DataCachesCard() {
  const { data: cacheStatus, refetch: refetchCache } = useCacheStatus()
  const { isRefreshing, startRefresh } = useCacheRefresh()
  const { data: gameDataCacheStats } = useGameDataCacheStats()
  const clearGameDataCacheMutation = useClearGameDataCache()
  const { data: matchCacheStats } = useMatchCacheStats()
  const clearAllMatchCacheMutation = useClearAllMatchCache()

  const handleRefreshCache = async () => {
    try {
      await startRefresh()
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 lg:divide-x">
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
              disabled={isRefreshing || cacheStatus?.refresh_in_progress}
              className="w-full mt-auto"
              size="sm"
            >
               {(isRefreshing || cacheStatus?.refresh_in_progress) && (
                <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />
              )}
               {isRefreshing || cacheStatus?.refresh_in_progress ? "Refreshing..." : "Refresh Directory"}
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
                <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />
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
                <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Clear Match Cache
            </Button>
          </div>

        </div>
      </CardContent>
    </Card>
  )
}

function RunHistoryCard() {
  const { data: settings } = useReconciliationSettings()
  const updateSettings = useUpdateReconciliationSettings()
  const { data: dbStatus, refetch: refetchDb } = useDatabaseStatus()
  const compactMutation = useCompactDatabase()
  const clearAllRunsMutation = useClearAllRuns()
  // Draft is null until the user edits, so the inputs track saved settings
  // without an effect; saving clears the draft back to the server values.
  const [draft, setDraft] = useState<{ detail: string; runs: string } | null>(null)
  const detailDays = draft?.detail ?? String(settings?.run_detail_retention_days ?? "")
  const runDays = draft?.runs ?? String(settings?.run_history_retention_days ?? "")
  const setDetailDays = (v: string) => setDraft({ detail: v, runs: runDays })
  const setRunDays = (v: string) => setDraft({ detail: detailDays, runs: v })

  const compaction = dbStatus?.compaction
  const detailRows = Object.values(dbStatus?.detail_rows ?? {}).reduce((a, b) => a + b, 0)
  const detailNum = Number(detailDays)
  const runNum = Number(runDays)
  const valid =
    Number.isInteger(detailNum) && detailNum >= 1 && detailNum <= 365 &&
    Number.isInteger(runNum) && runNum >= 1 && runNum <= 365
  const dirty =
    !!settings &&
    (detailNum !== settings.run_detail_retention_days ||
      runNum !== settings.run_history_retention_days)

  const handleSave = () => {
    if (!settings || !valid) return
    updateSettings.mutate(
      { ...settings, run_detail_retention_days: detailNum, run_history_retention_days: runNum },
      {
        onSuccess: () => {
          setDraft(null)
          toast.success("Retention saved — applies after the next generation run")
        },
        onError: () => toast.error("Failed to save retention"),
      },
    )
  }

  const handleCompact = () => {
    compactMutation.mutate(undefined, {
      onSuccess: () => toast.success("Compaction started"),
      onError: (err) => toast.error(err instanceof Error ? err.message : "Failed to start compaction"),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HardDrive className="h-5 w-5" />
          Database & Run History
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:divide-x">
          {/* Size */}
          <div className="flex flex-col gap-4 lg:pr-6">
            <h4 className="text-sm font-medium text-center">Database</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="text-center">
                <div className="text-2xl font-bold">
                  {dbStatus ? formatBytes(dbStatus.file_bytes) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">On disk</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">
                  {dbStatus ? formatBytes(dbStatus.reclaimable_bytes) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">Reclaimable</div>
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              {compaction?.running
                ? "Compacting… generation is paused until this finishes"
                : compaction?.error
                  ? `Last compaction failed: ${compaction.error}`
                  : compaction?.after_bytes != null && compaction.before_bytes != null
                    ? `Last compaction: ${formatBytes(compaction.before_bytes)} → ${formatBytes(compaction.after_bytes)}`
                    : "SQLite keeps freed space inside the file until it is compacted. Needs free disk roughly equal to the file size."}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCompact}
              disabled={compactMutation.isPending || !!compaction?.running}
              className="w-full mt-auto"
            >
              {compactMutation.isPending || compaction?.running ? (
                <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Shrink className="h-4 w-4 mr-2" />
              )}
              Compact Database
            </Button>
          </div>

          {/* Retention */}
          <div className="flex flex-col gap-4 lg:px-6">
            <h4 className="text-sm font-medium text-center">Retention</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="run-detail-days" className="text-xs">Per-stream detail (days)</Label>
                <Input
                  id="run-detail-days"
                  type="number"
                  min={1}
                  max={365}
                  value={detailDays}
                  onChange={(e) => setDetailDays(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="run-history-days" className="text-xs">Run summaries (days)</Label>
                <Input
                  id="run-history-days"
                  type="number"
                  min={1}
                  max={365}
                  value={runDays}
                  onChange={(e) => setRunDays(e.target.value)}
                />
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              Detail rows are the matched/unmatched stream lists behind each run — one row per
              stream per run, so a short generation interval needs a short window. Run
              summaries (counts, durations) are kept longer; all-time totals are never pruned.
            </div>
            <SaveButton
              size="sm"
              onClick={handleSave}
              pending={updateSettings.isPending}
              disabled={!dirty || !valid}
              className="w-full mt-auto"
            />
          </div>

          {/* Clear */}
          <div className="flex flex-col gap-4 lg:pl-6">
            <h4 className="text-sm font-medium text-center">Run History</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="text-center">
                <div className="text-2xl font-bold">{dbStatus?.run_count ?? 0}</div>
                <div className="text-xs text-muted-foreground">Runs</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold">{detailRows.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground">Detail rows</div>
              </div>
            </div>
            <div className="text-center text-xs text-muted-foreground">
              Pruned automatically after each generation run
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                clearAllRunsMutation.mutate(undefined, {
                  onSuccess: (data) => {
                    toast.success(data.message)
                    refetchDb()
                  },
                  onError: () => toast.error("Failed to clear run history"),
                })
              }}
              disabled={clearAllRunsMutation.isPending}
              className="w-full mt-auto"
            >
              {clearAllRunsMutation.isPending ? (
                <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />
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
      <GracenoteOverridesCard />
      <LogLevelCard />
      <DataCachesCard />
      <RunHistoryCard />
    </>
  )
}
