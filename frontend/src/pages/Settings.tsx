import { useState, useEffect, useMemo, useRef } from "react"
import { toast } from "sonner"
import cronstrue from "cronstrue"
import { cn, getSportDisplayName } from "@/lib/utils"
import {
  Loader2,
  Save,
  TestTube,
  Play,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Database,
  Plus,
  Trash2,
  Download,
  Upload,
  Pencil,
  Check,
  X,
  RefreshCw,
  ExternalLink,
  Shield,
  ShieldOff,
  HardDrive,
  ChevronDown,
  ChevronRight,
  Search,
} from "lucide-react"
import {
  ChannelProfileSelector,
  profileIdsToApi,
  apiToProfileIds,
} from "@/components/ChannelProfileSelector"
import { StreamProfileSelector } from "@/components/StreamProfileSelector"
import { useGenerationProgress } from "@/contexts/GenerationContext"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import {
  useSettings,
  useUpdateDispatcharrSettings,
  useTestDispatcharrConnection,
  useDispatcharrStatus,
  useDispatcharrEPGSources,
  useUpdateLifecycleSettings,
  useUpdateSchedulerSettings,
  useSchedulerStatus,
  useUpdateEPGSettings,
  useUpdateDurationSettings,
  useUpdateDisplaySettings,
  useExceptionKeywords,
  useCreateExceptionKeyword,
  useDeleteExceptionKeyword,
  useChannelNumberingSettings,
  useUpdateChannelNumberingSettings,
  useUpdateCheckSettings,
  useUpdateUpdateCheckSettings,
  useCheckForUpdates,
  useForceCheckForUpdates,
  useFeedSeparationSettings,
  useUpdateFeedSeparationSettings,
  useLeagueConfigs,
  useUpsertLeagueConfig,
  useDeleteLeagueConfig,
  useEmbySettings,
  useUpdateEmbySettings,
  useTestEmbyConnection,
  useJellyfinSettings,
  useUpdateJellyfinSettings,
  useTestJellyfinConnection,
} from "@/hooks/useSettings"
import { SortPriorityManager } from "@/components/SortPriorityManager"
import { StreamOrderingManager } from "@/components/StreamOrderingManager"
import { getLeagues, getSports } from "@/api/teams"
import { useSubscription } from "@/hooks/useSubscription"
import { restoreBackup, downloadSpecificBackup } from "@/api/backup"
import {
  useBackups,
  useCreateBackup,
  useDeleteBackup,
  useProtectBackup,
  useUnprotectBackup,
  useRestoreFromBackup,
  useBackupSettings,
  useUpdateBackupSettings,
} from "@/hooks/useBackup"
import { useQuery } from "@tanstack/react-query"
import { useCacheStatus, useRefreshCache, useGameDataCacheStats, useClearGameDataCache, useClearAllRuns, useMatchCacheStats, useClearAllMatchCache } from "@/hooks/useEPG"
import { useDateFormat } from "@/hooks/useDateFormat"
import type {
  DispatcharrSettings,
  LifecycleSettings,
  SchedulerSettings,
  EPGSettings,
  DurationSettings,
  DisplaySettings,
  ChannelNumberingSettings,
  UpdateCheckSettings,
  FeedSeparationSettings,
  EmbySettings,
  JellyfinSettings,
  SubscriptionLeagueConfig,
  TSDBKeyValidationResult,
} from "@/api/settings"
import { validateTSDBKey } from "@/api/settings"

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "Never"
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return "Just now"
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  return `${diffDays}d ago`
}

function CronPreview({ expression }: { expression: string }) {
  const humanReadable = useMemo(() => {
    try {
      return cronstrue.toString(expression, {
        throwExceptionOnParseError: false,
        verbose: true,
      })
    } catch {
      return null
    }
  }, [expression])

  if (!humanReadable) {
    return (
      <p className="text-xs text-destructive">Invalid cron expression</p>
    )
  }

  return (
    <p className="text-xs text-muted-foreground">
      {humanReadable}
    </p>
  )
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i]
}

function BackupRestoreCard() {
  // Backup settings state
  const { data: settings } = useBackupSettings()
  const updateSettings = useUpdateBackupSettings()
  const [localSettings, setLocalSettings] = useState({
    enabled: false,
    cron: "0 3 * * *",
    max_count: 7,
  })
  const [hasChanges, setHasChanges] = useState(false)

  // Backup files state
  const { data: backupsData, isLoading: backupsLoading, refetch } = useBackups()
  const createBackup = useCreateBackup()
  const deleteBackupMutation = useDeleteBackup()
  const protectBackupMutation = useProtectBackup()
  const unprotectBackupMutation = useUnprotectBackup()
  const restoreFromBackupMutation = useRestoreFromBackup()
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
  const [restoringFile, setRestoringFile] = useState<string | null>(null)

  // File upload restore state
  const [isRestoring, setIsRestoring] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (settings) {
      setLocalSettings({
        enabled: settings.enabled,
        cron: settings.cron,
        max_count: settings.max_count,
      })
      setHasChanges(false)
    }
  }, [settings])

  const handleSaveSettings = async () => {
    try {
      await updateSettings.mutateAsync(localSettings)
      toast.success("Backup settings saved")
      setHasChanges(false)
    } catch {
      toast.error("Failed to save backup settings")
    }
  }

  const handleCreateBackup = async () => {
    try {
      const result = await createBackup.mutateAsync()
      toast.success(`Backup created: ${result.filename}`)
    } catch {
      toast.error("Failed to create backup")
    }
  }

  const handleDelete = async (filename: string) => {
    if (!confirm(`Delete backup "${filename}"? This cannot be undone.`)) {
      return
    }
    setDeletingFile(filename)
    try {
      await deleteBackupMutation.mutateAsync(filename)
      toast.success("Backup deleted")
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to delete backup"
      toast.error(message)
    } finally {
      setDeletingFile(null)
    }
  }

  const handleToggleProtection = async (filename: string, isProtected: boolean) => {
    try {
      if (isProtected) {
        await unprotectBackupMutation.mutateAsync(filename)
        toast.success("Backup unprotected")
      } else {
        await protectBackupMutation.mutateAsync(filename)
        toast.success("Backup protected")
      }
    } catch {
      toast.error("Failed to update protection")
    }
  }

  const handleRestoreFromFile = async (filename: string) => {
    if (!confirm(`Restore from "${filename}"? This will replace ALL current data. A pre-restore backup will be created.`)) {
      return
    }
    setRestoringFile(filename)
    try {
      const result = await restoreFromBackupMutation.mutateAsync(filename)
      toast.success(result.message)
      if (result.backup_path) {
        toast.info(`Pre-restore backup saved at: ${result.backup_path}`)
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to restore backup"
      toast.error(message)
    } finally {
      setRestoringFile(null)
    }
  }

  const handleUploadRestore = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (!confirm("Restore from uploaded file? This will replace ALL current data. A pre-restore backup will be created.")) {
      event.target.value = ""
      return
    }

    setIsRestoring(true)
    try {
      const result = await restoreBackup(file)
      toast.success(result.message)
      if (result.backup_path) {
        toast.info(`Pre-restore backup saved at: ${result.backup_path}`)
      }
      refetch()
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to restore backup"
      toast.error(message)
    } finally {
      setIsRestoring(false)
      event.target.value = ""
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString() + " " + date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  }

  const presets = [
    { label: "Daily 3 AM", cron: "0 3 * * *" },
    { label: "Weekly (Sun)", cron: "0 3 * * 0" },
    { label: "Monthly (1st)", cron: "0 3 1 * *" },
  ]

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              Backup & Restore
            </CardTitle>
            <CardDescription>
              Manage database backups with scheduled automation and restore capabilities
            </CardDescription>
          </div>
          <Button
            size="sm"
            onClick={handleCreateBackup}
            disabled={createBackup.isPending}
          >
            {createBackup.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Plus className="h-4 w-4 mr-2" />
            )}
            Create Backup
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Scheduled Backups Section */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium border-b pb-2">Scheduled Backups</h4>

          <div className="flex items-center gap-3">
            <Switch
              checked={localSettings.enabled}
              onCheckedChange={(checked) => {
                setLocalSettings(prev => ({ ...prev, enabled: checked }))
                setHasChanges(true)
              }}
            />
            <div>
              <Label className="text-sm font-medium">Enable Scheduled Backups</Label>
              <p className="text-xs text-muted-foreground">
                Automatically create backups according to the schedule
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="space-y-2">
              <Label className="text-sm font-medium">Schedule</Label>
              <div className="flex gap-2 flex-wrap">
                {presets.map((preset) => (
                  <Button
                    key={preset.cron}
                    variant={localSettings.cron === preset.cron ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setLocalSettings(prev => ({ ...prev, cron: preset.cron }))
                      setHasChanges(true)
                    }}
                  >
                    {preset.label}
                  </Button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Input
                  value={localSettings.cron}
                  onChange={(e) => {
                    setLocalSettings(prev => ({ ...prev, cron: e.target.value }))
                    setHasChanges(true)
                  }}
                  placeholder="0 3 * * *"
                  className="font-mono text-sm"
                />
                <CronPreview expression={localSettings.cron} />
              </div>

              <div className="space-y-1">
                <Select
                  value={String(localSettings.max_count)}
                  onChange={(e) => {
                    setLocalSettings(prev => ({ ...prev, max_count: parseInt(e.target.value) }))
                    setHasChanges(true)
                  }}
                >
                  <option value="3">3 backups</option>
                  <option value="5">5 backups</option>
                  <option value="7">7 backups</option>
                  <option value="14">14 backups</option>
                  <option value="30">30 backups</option>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Max backups to keep (oldest deleted when exceeded)
                </p>
              </div>
            </div>

            <Button
              onClick={handleSaveSettings}
              disabled={!hasChanges || updateSettings.isPending}
              size="sm"
            >
              {updateSettings.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              Save Settings
            </Button>
          </div>
        </div>

        {/* Backup Files Section */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium border-b pb-2">Backup Files</h4>

          {backupsLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : !backupsData?.backups.length ? (
            <div className="text-center py-8 text-muted-foreground">
              <HardDrive className="h-12 w-12 mx-auto mb-2 opacity-20" />
              <p>No backup files found</p>
              <p className="text-xs">Create a backup to get started</p>
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">Filename</th>
                    <th className="text-left px-4 py-2 font-medium">Size</th>
                    <th className="text-left px-4 py-2 font-medium">Created</th>
                    <th className="text-left px-4 py-2 font-medium">Type</th>
                    <th className="text-right px-4 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {backupsData.backups.map((backup) => (
                    <tr key={backup.filename} className="hover:bg-muted/30">
                      <td className="px-4 py-2 font-mono text-xs">
                        <div className="flex items-center gap-2">
                          {backup.is_protected && (
                            <span title="Protected">
                              <Shield className="h-4 w-4 text-amber-500" />
                            </span>
                          )}
                          {backup.filename}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {formatBytes(backup.size_bytes)}
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {formatDate(backup.created_at)}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={backup.backup_type === "scheduled" ? "secondary" : "outline"}>
                          {backup.backup_type}
                        </Badge>
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => downloadSpecificBackup(backup.filename)}
                            title="Download"
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleRestoreFromFile(backup.filename)}
                            disabled={restoringFile === backup.filename}
                            title="Restore"
                          >
                            {restoringFile === backup.filename ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Upload className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleToggleProtection(backup.filename, backup.is_protected)}
                            title={backup.is_protected ? "Unprotect" : "Protect"}
                          >
                            {backup.is_protected ? (
                              <ShieldOff className="h-4 w-4" />
                            ) : (
                              <Shield className="h-4 w-4" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            onClick={() => handleDelete(backup.filename)}
                            disabled={deletingFile === backup.filename || backup.is_protected}
                            title={backup.is_protected ? "Cannot delete protected backup" : "Delete"}
                          >
                            {deletingFile === backup.filename ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Trash2 className="h-4 w-4" />
                            )}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Restore from File Section */}
        <div className="space-y-4">
          <h4 className="text-sm font-medium border-b pb-2">Restore from File</h4>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <p className="text-xs text-muted-foreground mb-2">
                Upload a .db backup file to restore. A pre-restore backup will be created first.
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".db"
                onChange={handleUploadRestore}
                className="hidden"
              />
              <Button
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                disabled={isRestoring}
              >
                {isRestoring ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4 mr-2" />
                )}
                {isRestoring ? "Restoring..." : "Upload & Restore"}
              </Button>
            </div>
          </div>
        </div>

        {/* Warning */}
        <div className="rounded-md bg-amber-500/10 border border-amber-500/20 p-3">
          <div className="flex gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-500">
              <p className="font-medium">Important</p>
              <p className="text-xs">
                Restoring a backup will replace ALL current data. The application needs to be restarted for changes to take effect.
                Protected backups (<Shield className="h-3 w-3 inline" />) are excluded from automatic rotation.
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// Per-League Config Row Component
function LeagueConfigRow({
  leagueName,
  sportName,
  config,
  isExpanded,
  hasOverride,
  channelProfiles,
  channelGroups,
  dispatcharrConnected,
  onToggleExpand,
  onSave,
  onClear,
}: {
  leagueName: string
  sportName: string
  config: SubscriptionLeagueConfig | null
  isExpanded: boolean
  hasOverride: boolean
  channelProfiles: { id: number; name: string }[]
  channelGroups: { id: number; name: string }[]
  dispatcharrConnected: boolean
  onToggleExpand: () => void
  onSave: (data: {
    channel_profile_ids?: (number | string)[] | null
    channel_group_id?: number | null
    channel_group_mode?: string | null
  }) => Promise<void>
  onClear: () => Promise<void>
}) {
  const [localProfileIds, setLocalProfileIds] = useState<(number | string)[]>([])
  const [localGroupId, setLocalGroupId] = useState<number | null>(null)
  const [localGroupMode, setLocalGroupMode] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Sync local state when config changes or row expands
  useEffect(() => {
    if (isExpanded && config) {
      setLocalProfileIds(
        config.channel_profile_ids !== null && config.channel_profile_ids !== undefined
          ? config.channel_profile_ids
          : []
      )
      setLocalGroupId(config.channel_group_id)
      setLocalGroupMode(config.channel_group_mode)
    } else if (isExpanded && !config) {
      setLocalProfileIds([])
      setLocalGroupId(null)
      setLocalGroupMode(null)
    }
  }, [isExpanded, config])

  const profileSummary = (() => {
    if (!config?.channel_profile_ids) return "Default"
    if (config.channel_profile_ids.length === 0) return "None"
    const names = config.channel_profile_ids.map((id) => {
      if (typeof id === "string") return id
      const p = channelProfiles.find((cp) => cp.id === id)
      return p?.name ?? `#${id}`
    })
    return names.length <= 2 ? names.join(", ") : `${names.length} profiles`
  })()

  const groupSummary = (() => {
    if (!config?.channel_group_id) return "Default"
    const g = channelGroups.find((cg) => cg.id === config.channel_group_id)
    return g?.name ?? `#${config.channel_group_id}`
  })()

  const modeSummary = (() => {
    const mode = config?.channel_group_mode
    if (!mode) return "Default"
    if (mode === "static") return "Static"
    if (mode === "sport") return "Sport"
    if (mode === "league") return "League"
    return `Custom: ${mode}`
  })()

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave({
        channel_profile_ids: localProfileIds.length > 0 ? localProfileIds : null,
        channel_group_id: localGroupId,
        channel_group_mode: localGroupMode,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <tr
        className={cn(
          "hover:bg-muted/30 cursor-pointer",
          hasOverride && "bg-primary/5",
          isExpanded && "bg-accent"
        )}
        onClick={onToggleExpand}
      >
        <td className="px-3 py-1.5">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </td>
        <td className="px-3 py-1.5 text-muted-foreground">{sportName}</td>
        <td className="px-3 py-1.5">{leagueName}</td>
        <td className="px-3 py-1.5">
          <span className={cn("text-xs", !hasOverride && "text-muted-foreground")}>
            {profileSummary}
          </span>
        </td>
        <td className="px-3 py-1.5">
          <span className={cn("text-xs", !hasOverride && "text-muted-foreground")}>
            {groupSummary}
          </span>
        </td>
        <td className="px-3 py-1.5">
          <span className={cn("text-xs", !hasOverride && "text-muted-foreground")}>
            {modeSummary}
          </span>
        </td>
        <td className="px-3 py-1.5 text-right">
          {hasOverride && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={(e) => {
                e.stopPropagation()
                onClear()
              }}
              title="Clear override"
            >
              <X className="h-3 w-3 text-muted-foreground" />
            </Button>
          )}
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={7} className="px-4 py-3 bg-muted/20 border-t-0">
            <div className="space-y-4 max-w-2xl">
              {/* Channel Profiles */}
              <div>
                <Label className="text-sm font-medium">Channel Profiles</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  Override which channel profiles this league's channels are assigned to.
                  Leave empty to inherit global default.
                </p>
                <ChannelProfileSelector
                  selectedIds={localProfileIds}
                  onChange={setLocalProfileIds}
                  disabled={!dispatcharrConnected}
                />
              </div>

              {/* Channel Group */}
              <div>
                <Label className="text-sm font-medium">Channel Group</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  Override which Dispatcharr channel group this league's channels are placed in.
                </p>
                <Select
                  value={localGroupId?.toString() ?? ""}
                  onChange={(e) => {
                    const v = e.target.value
                    setLocalGroupId(v ? parseInt(v) : null)
                  }}
                  disabled={!dispatcharrConnected}
                  className="w-64"
                >
                  <option value="">Default (inherit)</option>
                  {channelGroups.map((g) => (
                    <option key={g.id} value={g.id.toString()}>
                      {g.name}
                    </option>
                  ))}
                </Select>
              </div>

              {/* Channel Group Mode */}
              <div>
                <Label className="text-sm font-medium">Channel Group Mode</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  How the channel group is determined: static (use selected group), or dynamic by sport/league name.
                </p>
                <Select
                  value={
                    localGroupMode && !["static", "sport", "league"].includes(localGroupMode)
                      ? "custom"
                      : localGroupMode ?? ""
                  }
                  onChange={(e) => {
                    const v = e.target.value
                    if (v === "custom") {
                      setLocalGroupMode("{sport} | {league}")
                    } else {
                      setLocalGroupMode(v || null)
                    }
                  }}
                  className="w-64"
                >
                  <option value="">Default (inherit)</option>
                  <option value="static">Static (use selected group)</option>
                  <option value="sport">Dynamic by Sport</option>
                  <option value="league">Dynamic by League</option>
                  <option value="custom">Custom pattern</option>
                </Select>
                {localGroupMode && !["static", "sport", "league"].includes(localGroupMode) && (
                  <Input
                    value={localGroupMode}
                    onChange={(e) => setLocalGroupMode(e.target.value)}
                    placeholder="{sport} | {league}"
                    className="w-64 mt-2"
                  />
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-1">
                <Button
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleSave()
                  }}
                  disabled={saving}
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4 mr-1" />
                  )}
                  Save
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggleExpand()
                  }}
                >
                  Cancel
                </Button>
                {hasOverride && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      onClear()
                    }}
                  >
                    <Trash2 className="h-4 w-4 mr-1" />
                    Clear Override
                  </Button>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

type SettingsTab = "general" | "teams" | "events" | "channels" | "epg" | "dispatcharr" | "media-servers" | "advanced"

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "teams", label: "Teams" },
  { id: "events", label: "Event Groups" },
  { id: "epg", label: "EPG" },
  { id: "channels", label: "Channels" },
  { id: "dispatcharr", label: "Dispatcharr" },
  { id: "media-servers", label: "Media Servers" },
  { id: "advanced", label: "System" },
]

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general")
  const { data: settings, isLoading, error, refetch } = useSettings()
  const dispatcharrStatus = useDispatcharrStatus()
  const epgSourcesQuery = useDispatcharrEPGSources(dispatcharrStatus.data?.connected ?? false)

  // Fetch channel profiles for conversion helpers
  const channelProfilesQuery = useQuery({
    queryKey: ["dispatcharr-channel-profiles"],
    queryFn: async () => {
      const response = await fetch("/api/v1/dispatcharr/channel-profiles")
      if (!response.ok) return []
      return response.json() as Promise<{ id: number; name: string }[]>
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })
  const schedulerStatus = useSchedulerStatus()
  const { data: cacheStatus, refetch: refetchCache } = useCacheStatus()
  const refreshCacheMutation = useRefreshCache()
  const { data: gameDataCacheStats } = useGameDataCacheStats()
  const clearGameDataCacheMutation = useClearGameDataCache()
  const clearAllRunsMutation = useClearAllRuns()
  const { data: matchCacheStats } = useMatchCacheStats()
  const clearAllMatchCacheMutation = useClearAllMatchCache()
  const { startGeneration, isGenerating } = useGenerationProgress()

  const updateDispatcharr = useUpdateDispatcharrSettings()
  const testConnection = useTestDispatcharrConnection()
  const updateLifecycle = useUpdateLifecycleSettings()
  const updateScheduler = useUpdateSchedulerSettings()
  const updateEPG = useUpdateEPGSettings()
  const updateDurations = useUpdateDurationSettings()
  const updateDisplay = useUpdateDisplaySettings()

  // Subscription for league filtering
  const { data: subscription } = useSubscription()
  const subscribedLeagueSlugs = useMemo(
    () => new Set(subscription?.leagues ?? []),
    [subscription]
  )

  // Exception keywords
  const keywordsQuery = useExceptionKeywords()
  const createKeyword = useCreateExceptionKeyword()
  const deleteKeyword = useDeleteExceptionKeyword()

  // Channel numbering settings
  const { data: channelNumberingData } = useChannelNumberingSettings()
  const updateChannelNumbering = useUpdateChannelNumberingSettings()

  // Feed separation settings
  const { data: feedSeparationData } = useFeedSeparationSettings()
  const updateFeedSeparation = useUpdateFeedSeparationSettings()

  // Emby settings
  const { data: embyData } = useEmbySettings()
  const updateEmby = useUpdateEmbySettings()
  const testEmby = useTestEmbyConnection()

  // Jellyfin settings
  const { data: jellyfinData } = useJellyfinSettings()
  const updateJellyfin = useUpdateJellyfinSettings()
  const testJellyfin = useTestJellyfinConnection()

  // Per-league subscription config
  const { data: leagueConfigsData } = useLeagueConfigs()
  const upsertLeagueConfigMutation = useUpsertLeagueConfig()
  const deleteLeagueConfigMutation = useDeleteLeagueConfig()

  // Update check settings
  const { data: updateCheckData } = useUpdateCheckSettings()
  const updateUpdateCheck = useUpdateUpdateCheckSettings()
  const updateInfoQuery = useCheckForUpdates(updateCheckData?.enabled ?? true)
  const forceCheckUpdates = useForceCheckForUpdates()
  const { formatDateTime } = useDateFormat()

  const { data: leaguesData } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(),
  })

  // Fetch sport display names from database (single source of truth)
  const { data: sportsData } = useQuery({
    queryKey: ["sports"],
    queryFn: getSports,
    staleTime: 1000 * 60 * 60, // 1 hour
  })
  const sportsMap = sportsData?.sports

  // Local form state
  const [dispatcharr, setDispatcharr] = useState<Partial<DispatcharrSettings>>({})
  const [lifecycle, setLifecycle] = useState<LifecycleSettings | null>(null)
  const [scheduler, setScheduler] = useState<SchedulerSettings | null>(null)
  const [epg, setEPG] = useState<EPGSettings | null>(null)
  const [durations, setDurations] = useState<DurationSettings | null>(null)
  const [display, setDisplay] = useState<DisplaySettings | null>(null)
  const [tsdbValidation, setTsdbValidation] = useState<TSDBKeyValidationResult | null>(null)
  const [tsdbValidating, setTsdbValidating] = useState(false)
  const [channelNumbering, setChannelNumbering] = useState<ChannelNumberingSettings>({
    global_channel_mode: "auto",
    league_channel_starts: {},
    global_consolidation_mode: "consolidate",
  })
  const [updateCheck, setUpdateCheck] = useState<UpdateCheckSettings>({
    enabled: true,
    notify_stable: true,
    notify_dev: true,
    github_owner: "Pharaoh-Labs",
    github_repo: "teamarr",
    dev_branch: "dev",
    auto_detect_branch: true,
  })
  const [feedSeparation, setFeedSeparation] = useState<FeedSeparationSettings>({
    enabled: false,
    home_terms: ["HOME"],
    away_terms: ["AWAY"],
    detect_team_names: true,
    label_style: "team_name",
  })
  const [emby, setEmby] = useState<Partial<EmbySettings>>({
    enabled: false,
    url: null,
    username: null,
    password: null,
    api_key: null,
  })
  const [embyTestResult, setEmbyTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [jellyfin, setJellyfin] = useState<Partial<JellyfinSettings>>({
    enabled: false,
    url: null,
    username: null,
    password: null,
    api_key: null,
  })
  const [jellyfinTestResult, setJellyfinTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [newKeyword, setNewKeyword] = useState({ label: "", match_terms: "", behavior: "consolidate" })
  const [editingKeyword, setEditingKeyword] = useState<{ id: number; label: string; match_terms: string } | null>(null)

  // Local state for channel range inputs (allows free typing)
  const [channelRangeStart, setChannelRangeStart] = useState("")
  const [channelRangeEnd, setChannelRangeEnd] = useState("")

  // Selected profile IDs for display (converted from API format)
  const [selectedProfileIds, setSelectedProfileIds] = useState<(number | string)[]>([])

  // Per-league config expanded row state
  const [expandedLeagueConfig, setExpandedLeagueConfig] = useState<string | null>(null)

  // League table filter state (shared between channel numbering and per-league config)
  const [leagueSearch, setLeagueSearch] = useState("")
  const [showSubscribedOnly, setShowSubscribedOnly] = useState(true)

  const filteredLeagues = useMemo(() => {
    const all = leaguesData?.leagues ?? []
    const searchLower = leagueSearch.toLowerCase()
    return all
      .filter((l) => {
        if (showSubscribedOnly && !subscribedLeagueSlugs.has(l.slug)) return false
        if (searchLower && !l.name.toLowerCase().includes(searchLower)
            && !l.sport.toLowerCase().includes(searchLower)) return false
        return true
      })
      .sort((a, b) => {
        const sportCmp = a.sport.localeCompare(b.sport)
        if (sportCmp !== 0) return sportCmp
        return a.name.localeCompare(b.name)
      })
  }, [leaguesData, leagueSearch, showSubscribedOnly, subscribedLeagueSlugs])

  // Dispatcharr channel groups for per-league config.
  // includeM3uGroups toggles the exclude_m3u backend filter — off by default
  // since most users don't want M3U-tagged groups in the picker, but some
  // hand-curate them and need access (see beads-5yi).
  const [includeM3uGroups, setIncludeM3uGroups] = useState(false)
  const channelGroupsQuery = useQuery({
    queryKey: ["dispatcharr-channel-groups", includeM3uGroups],
    queryFn: async () => {
      const url = includeM3uGroups
        ? "/api/v1/dispatcharr/channel-groups?exclude_m3u=false"
        : "/api/v1/dispatcharr/channel-groups"
      const response = await fetch(url)
      if (!response.ok) return []
      return response.json() as Promise<{ id: number; name: string }[]>
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })

  const initializedRef = useRef(false)

  // Initialize local state from settings (only once on initial load)
  useEffect(() => {
    if (settings && !initializedRef.current) {
      initializedRef.current = true
      setDispatcharr({
        enabled: settings.dispatcharr.enabled,
        url: settings.dispatcharr.url,
        username: settings.dispatcharr.username,
        password: "", // Don't show masked password
        epg_id: settings.dispatcharr.epg_id,
        default_channel_profile_ids: settings.dispatcharr.default_channel_profile_ids,
        default_stream_profile_id: settings.dispatcharr.default_stream_profile_id,
        default_channel_group_id: settings.dispatcharr.default_channel_group_id,
        default_channel_group_mode: settings.dispatcharr.default_channel_group_mode,
        cleanup_unused_logos: settings.dispatcharr.cleanup_unused_logos,
      })
      setLifecycle(settings.lifecycle)
      setScheduler(settings.scheduler)
      setEPG(settings.epg)
      setDurations(settings.durations)
      if (settings.display) {
        setDisplay(settings.display)
      }
    }
  }, [settings])

  // Sync channel numbering state when data loads
  useEffect(() => {
    if (channelNumberingData) {
      setChannelNumbering(channelNumberingData)
    }
  }, [channelNumberingData])

  // Sync update check state when data loads
  useEffect(() => {
    if (updateCheckData) {
      setUpdateCheck(updateCheckData)
    }
  }, [updateCheckData])

  // Sync feed separation state when data loads
  useEffect(() => {
    if (feedSeparationData) {
      setFeedSeparation(feedSeparationData)
    }
  }, [feedSeparationData])

  // Sync emby state when data loads
  useEffect(() => {
    if (embyData) {
      setEmby({
        enabled: embyData.enabled,
        url: embyData.url,
        username: embyData.username,
        password: "", // Don't show masked password
        api_key: "", // Don't show masked API key
      })
    }
  }, [embyData])

  // Sync jellyfin state when data loads
  useEffect(() => {
    if (jellyfinData) {
      setJellyfin({
        enabled: jellyfinData.enabled,
        url: jellyfinData.url,
        username: jellyfinData.username,
        password: "", // Don't show masked password
        api_key: "", // Don't show masked API key
      })
    }
  }, [jellyfinData])

  // Sync channel range inputs from lifecycle on initial load only
  const channelRangeInitializedRef = useRef(false)
  useEffect(() => {
    if (lifecycle && !channelRangeInitializedRef.current) {
      channelRangeInitializedRef.current = true
      setChannelRangeStart(lifecycle.channel_range_start?.toString() ?? "101")
      setChannelRangeEnd(lifecycle.channel_range_end?.toString() ?? "")
    }
  }, [lifecycle])

  // Convert API profile IDs to display IDs when profiles are loaded
  useEffect(() => {
    if (channelProfilesQuery.data && settings) {
      const allProfileIds = channelProfilesQuery.data.map(p => p.id)
      const displayIds = apiToProfileIds(
        settings.dispatcharr.default_channel_profile_ids,
        allProfileIds
      )
      setSelectedProfileIds(displayIds)
    }
  }, [channelProfilesQuery.data, settings])

  const handleSaveDispatcharr = async () => {
    try {
      // Convert selected profile IDs to API format
      // All selected → null (backend sends [0] sentinel to Dispatcharr)
      // None selected → [] (no profiles)
      // Some selected → those specific IDs
      const allProfileIds = channelProfilesQuery.data?.map(p => p.id) ?? []
      const profileIdsToSave = profileIdsToApi(selectedProfileIds, allProfileIds)

      // Only send password if it was changed
      const data: Partial<DispatcharrSettings> = {
        enabled: dispatcharr.enabled,
        url: dispatcharr.url,
        username: dispatcharr.username,
        epg_id: dispatcharr.epg_id,
        default_channel_profile_ids: profileIdsToSave,
        default_stream_profile_id: dispatcharr.default_stream_profile_id,
        default_channel_group_id: dispatcharr.default_channel_group_id,
        default_channel_group_mode: dispatcharr.default_channel_group_mode,
        cleanup_unused_logos: dispatcharr.cleanup_unused_logos,
      }
      if (dispatcharr.password) {
        data.password = dispatcharr.password
      }
      await updateDispatcharr.mutateAsync(data)
      toast.success("Dispatcharr settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTestConnection = async () => {
    try {
      const result = await testConnection.mutateAsync({
        url: dispatcharr.url || undefined,
        username: dispatcharr.username || undefined,
        password: dispatcharr.password || undefined,
      })
      if (result.success) {
        toast.success(`Connected! ${result.account_count} accounts, ${result.group_count} groups, ${result.channel_count} channels`)
      } else {
        toast.error(result.error || "Connection failed")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Connection test failed")
    }
  }

  const handleSaveEmby = async () => {
    try {
      const data: Partial<EmbySettings> = {
        enabled: emby.enabled,
        url: emby.url,
        username: emby.username,
      }
      if (emby.password) {
        data.password = emby.password
      }
      if (emby.api_key) {
        data.api_key = emby.api_key
      }
      await updateEmby.mutateAsync(data)
      toast.success("Emby settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTestEmby = async () => {
    try {
      setEmbyTestResult(null)
      const result = await testEmby.mutateAsync({
        url: emby.url || undefined,
        username: emby.username || undefined,
        password: emby.password || undefined,
        api_key: emby.api_key || undefined,
      })
      if (result.success) {
        setEmbyTestResult({
          success: true,
          message: `Connected to ${result.server_name || "Emby"} (v${result.server_version || "unknown"})`,
        })
      } else {
        setEmbyTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setEmbyTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      })
    }
  }

  const handleSaveJellyfin = async () => {
    try {
      const data: Partial<JellyfinSettings> = {
        enabled: jellyfin.enabled,
        url: jellyfin.url,
        username: jellyfin.username,
      }
      if (jellyfin.password) {
        data.password = jellyfin.password
      }
      if (jellyfin.api_key) {
        data.api_key = jellyfin.api_key
      }
      await updateJellyfin.mutateAsync(data)
      toast.success("Jellyfin settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTestJellyfin = async () => {
    try {
      setJellyfinTestResult(null)
      const result = await testJellyfin.mutateAsync({
        url: jellyfin.url || undefined,
        username: jellyfin.username || undefined,
        password: jellyfin.password || undefined,
        api_key: jellyfin.api_key || undefined,
      })
      if (result.success) {
        setJellyfinTestResult({
          success: true,
          message: `Connected to ${result.server_name || "Jellyfin"} (v${result.server_version || "unknown"})`,
        })
      } else {
        setJellyfinTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setJellyfinTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      })
    }
  }

  const handleTriggerRun = () => {
    // Use the same streaming endpoint as "Generate EPG" - full workflow with progress
    startGeneration()
  }

  const handleSaveDurations = async () => {
    if (!durations) return
    try {
      await updateDurations.mutateAsync(durations)
      toast.success("Duration settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleRefreshCache = async () => {
    try {
      const result = await refreshCacheMutation.mutateAsync()
      toast.success(result.message)
      refetchCache()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start cache refresh")
    }
  }

  const handleSaveDisplay = async (message?: string) => {
    if (!display) return
    try {
      await updateDisplay.mutateAsync(display)
      toast.success(message || "Display settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  // Combined save for sections that need both EPG and Display settings
  const handleSaveEPGAndDisplay = async () => {
    try {
      const promises: Promise<unknown>[] = []
      if (display) promises.push(updateDisplay.mutateAsync(display))
      if (epg) promises.push(updateEPG.mutateAsync(epg))
      await Promise.all(promises)
      toast.success("Settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  // Combined save for scheduler settings
  const handleSaveSchedulerSettings = async () => {
    try {
      const promises: Promise<unknown>[] = []
      if (epg) promises.push(updateEPG.mutateAsync(epg))
      if (scheduler) promises.push(updateScheduler.mutateAsync(scheduler))
      await Promise.all(promises)
      toast.success("Settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleSaveChannelNumbering = async () => {
    try {
      // Save both channel numbering AND lifecycle settings (channel range is in lifecycle)
      const promises: Promise<unknown>[] = [
        updateChannelNumbering.mutateAsync(channelNumbering),
      ]
      if (lifecycle) {
        promises.push(updateLifecycle.mutateAsync(lifecycle))
      }
      await Promise.all(promises)
      toast.success("Channel numbering settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleAddKeyword = async () => {
    if (!newKeyword.label.trim()) {
      toast.error("Please enter a label")
      return
    }
    if (!newKeyword.match_terms.trim()) {
      toast.error("Please enter at least one match term")
      return
    }
    try {
      await createKeyword.mutateAsync(newKeyword)
      setNewKeyword({ label: "", match_terms: "", behavior: "consolidate" })
      toast.success("Keyword added")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add keyword")
    }
  }

  const handleDeleteKeyword = async (id: number) => {
    try {
      await deleteKeyword.mutateAsync(id)
      toast.success("Keyword deleted")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete keyword")
    }
  }

  const handleSaveKeywordEdit = async () => {
    if (!editingKeyword || !editingKeyword.label.trim()) {
      toast.error("Label cannot be empty")
      return
    }
    if (!editingKeyword.match_terms.trim()) {
      toast.error("Match terms cannot be empty")
      return
    }
    try {
      await fetch(`/api/v1/keywords/${editingKeyword.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: editingKeyword.label, match_terms: editingKeyword.match_terms }),
      })
      keywordsQuery.refetch()
      setEditingKeyword(null)
      toast.success("Keyword updated")
    } catch (err) {
      toast.error("Failed to update keyword")
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-bold">Settings</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">Error loading settings: {error.message}</p>
            <Button className="mt-4" onClick={() => refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div>
        <h1 className="text-xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">Configure Teamarr application settings</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 border-b border-border pb-px">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1.5 text-sm font-medium rounded-t transition-colors ${
              activeTab === tab.id
                ? "bg-card text-foreground border border-border border-b-card -mb-px"
                : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="space-y-3 min-h-[400px]">

      {/* General Tab */}
      {activeTab === "general" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">General Settings</h2>
        <p className="text-sm text-muted-foreground">Configure timezone, time format, and display preferences</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Display Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {/* Left column: Timezones */}
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ui-timezone">UI Display Timezone</Label>
                <Input
                  id="ui-timezone"
                  value={settings?.ui_timezone ?? "America/New_York"}
                  disabled
                  readOnly
                  className="bg-muted cursor-not-allowed"
                />
                <p className="text-xs text-muted-foreground">
                  This can be changed by setting the TZ environment variable
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="epg-timezone">EPG Output Timezone</Label>
                <Input
                  id="epg-timezone"
                  value={epg?.epg_timezone ?? "America/New_York"}
                  onChange={(e) => epg && setEPG({ ...epg, epg_timezone: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  Used for template variables like {"{game_time}"}
                </p>
              </div>
            </div>

            {/* Right column: Time Format and Show Timezone */}
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Time Format</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={display?.time_format === "12h" ? "default" : "outline"}
                    size="sm"
                    onClick={() => display && setDisplay({ ...display, time_format: "12h" })}
                  >
                    12-hour
                  </Button>
                  <Button
                    type="button"
                    variant={display?.time_format === "24h" ? "default" : "outline"}
                    size="sm"
                    onClick={() => display && setDisplay({ ...display, time_format: "24h" })}
                  >
                    24-hour
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Applies to UI display and EPG output
                </p>
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={display?.show_timezone ?? true}
                    onCheckedChange={(checked) =>
                      display && setDisplay({ ...display, show_timezone: checked })
                    }
                  />
                  <Label>Show Timezone Abbreviation</Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  Applies to UI display and EPG output
                </p>
              </div>
            </div>
          </div>

          {/* Info box when timezones differ */}
          {settings?.ui_timezone_source === "env" &&
           settings?.ui_timezone !== epg?.epg_timezone && (
            <div className="p-3 bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-md text-sm">
              <p className="font-medium text-blue-900 dark:text-blue-100">Two timezones configured:</p>
              <ul className="list-disc list-inside mt-1 text-blue-800 dark:text-blue-200">
                <li><strong>UI Display</strong>: {settings.ui_timezone} (from $TZ)</li>
                <li><strong>EPG Output</strong>: {epg?.epg_timezone} (user setting)</li>
              </ul>
            </div>
          )}

          <Button
            onClick={handleSaveEPGAndDisplay}
            disabled={updateDisplay.isPending || updateEPG.isPending}
          >
            {(updateDisplay.isPending || updateEPG.isPending) ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>
      </>
      )}

      {/* Teams Tab */}
      {activeTab === "teams" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Team Based Streams</h2>
        <p className="text-sm text-muted-foreground">Configure settings for team-based EPG generation</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Team EPG Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="team-schedule-days">Schedule Days Ahead</Label>
              <Select
                id="team-schedule-days"
                value={String(epg?.team_schedule_days_ahead ?? 30)}
                onChange={(e) =>
                  epg && setEPG({ ...epg, team_schedule_days_ahead: parseInt(e.target.value) })
                }
              >
                <option value="7">7 days</option>
                <option value="14">14 days</option>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
                <option value="90">90 days</option>
              </Select>
              <p className="text-xs text-muted-foreground">
                How far to fetch team schedules (for .next variables)
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="midnight-mode">Midnight Crossover</Label>
              <Select
                id="midnight-mode"
                value={epg?.midnight_crossover_mode ?? "postgame"}
                onChange={(e) =>
                  epg && setEPG({ ...epg, midnight_crossover_mode: e.target.value })
                }
              >
                <option value="postgame">Show postgame filler</option>
                <option value="idle">Show idle filler</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="channel-id-format">Channel ID Format</Label>
              <Input
                id="channel-id-format"
                value={display?.channel_id_format ?? "{team_name_pascal}.{league}"}
                onChange={(e) => display && setDisplay({ ...display, channel_id_format: e.target.value })}
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                {"{team_name}"}, {"{league}"}, {"{league_id}"}
              </p>
            </div>
          </div>

          <Button
            onClick={handleSaveEPGAndDisplay}
            disabled={updateEPG.isPending || updateDisplay.isPending}
          >
            {(updateEPG.isPending || updateDisplay.isPending) ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>
      </>
      )}

      {/* Event Groups Tab */}
      {activeTab === "events" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Event Based Streams</h2>
        <p className="text-sm text-muted-foreground">Configure settings for event-based EPG generation (Event Groups)</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Event Matching</CardTitle>
          <CardDescription>
            Configure how streams are matched to sporting events
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="event-lookahead">Event Lookahead</Label>
            <Select
              id="event-lookahead"
              value={String(epg?.event_match_days_ahead ?? 3)}
              onChange={(e) =>
                epg && setEPG({
                  ...epg,
                  event_match_days_ahead: parseInt(e.target.value),
                })
              }
            >
              <option value="1">1 day</option>
              <option value="3">3 days</option>
              <option value="7">7 days</option>
              <option value="14">14 days</option>
              <option value="30">30 days</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              How far ahead to match streams to events
            </p>
          </div>

          <Button
            onClick={async () => {
              try {
                if (epg) await updateEPG.mutateAsync(epg)
                toast.success("Event matching settings saved")
              } catch (err) {
                toast.error(
                  err instanceof Error ? err.message : "Failed to save"
                )
              }
            }}
            disabled={updateEPG.isPending}
          >
            {updateEPG.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Exception Keywords Card */}
      {channelNumbering.global_consolidation_mode === "consolidate" && (
      <Card>
        <CardHeader>
          <CardTitle>Exception Keywords</CardTitle>
          <CardDescription>
            Streams matching these terms get special handling during consolidation. The label is used for channel naming and the {"{exception_keyword}"} template variable.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="border rounded-md">
            <table className="w-full text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium w-32">Label</th>
                  <th className="px-3 py-2 text-left font-medium">Match Terms (comma-separated)</th>
                  <th className="px-3 py-2 text-left font-medium w-40">Behavior</th>
                  <th className="px-3 py-2 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {keywordsQuery.data?.keywords.map((kw) => (
                  <tr key={kw.id} className="border-t">
                    <td className="px-3 py-2">
                      {editingKeyword?.id === kw.id ? (
                        <Input
                          value={editingKeyword.label}
                          onChange={(e) => setEditingKeyword({ ...editingKeyword, label: e.target.value })}
                          className="h-8"
                          autoFocus
                          placeholder="Label"
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveKeywordEdit()
                            if (e.key === "Escape") setEditingKeyword(null)
                          }}
                        />
                      ) : (
                        <span className="font-medium">{kw.label}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {editingKeyword?.id === kw.id ? (
                        <Input
                          value={editingKeyword.match_terms}
                          onChange={(e) => setEditingKeyword({ ...editingKeyword, match_terms: e.target.value })}
                          className="h-8"
                          placeholder="Terms to match"
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveKeywordEdit()
                            if (e.key === "Escape") setEditingKeyword(null)
                          }}
                        />
                      ) : (
                        <span className="text-muted-foreground">{kw.match_terms}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Select
                        value={kw.behavior}
                        onChange={async (e) => {
                          const newBehavior = e.target.value
                          try {
                            await fetch(`/api/v1/keywords/${kw.id}`, {
                              method: "PUT",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ behavior: newBehavior }),
                            })
                            keywordsQuery.refetch()
                            toast.success(`Updated behavior to "${newBehavior}"`)
                          } catch (err) {
                            toast.error("Failed to update keyword behavior")
                          }
                        }}
                        className="w-40 h-8"
                        disabled={editingKeyword?.id === kw.id}
                      >
                        <option value="consolidate">Sub-Consolidate</option>
                        <option value="separate">Separate</option>
                        <option value="ignore">Ignore</option>
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        {editingKeyword?.id === kw.id ? (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={handleSaveKeywordEdit}
                              title="Save"
                            >
                              <Check className="h-4 w-4 text-green-600" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditingKeyword(null)}
                              title="Cancel"
                            >
                              <X className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditingKeyword({ id: kw.id, label: kw.label, match_terms: kw.match_terms })}
                              title="Edit"
                            >
                              <Pencil className="h-4 w-4 text-muted-foreground" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDeleteKeyword(kw.id)}
                              disabled={deleteKeyword.isPending}
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {(!keywordsQuery.data?.keywords || keywordsQuery.data.keywords.length === 0) && (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">
                      No exception keywords defined
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex gap-2">
            <Input
              placeholder="Label (e.g., Spanish)"
              value={newKeyword.label}
              onChange={(e) => setNewKeyword({ ...newKeyword, label: e.target.value })}
              className="w-32"
            />
            <Input
              placeholder="Match terms (e.g., Spanish, En Español, ESP)"
              value={newKeyword.match_terms}
              onChange={(e) => setNewKeyword({ ...newKeyword, match_terms: e.target.value })}
              className="flex-1"
            />
            <Select
              value={newKeyword.behavior}
              onChange={(e) => setNewKeyword({ ...newKeyword, behavior: e.target.value })}
              className="w-40"
            >
              <option value="consolidate">Sub-Consolidate</option>
              <option value="separate">Separate</option>
              <option value="ignore">Ignore</option>
            </Select>
            <Button onClick={handleAddKeyword} disabled={createKeyword.isPending}>
              {createKeyword.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
      )}

      {/* Feed Separation (HOME/AWAY Detection) */}
      <Card>
        <CardHeader>
          <CardTitle>Feed Separation</CardTitle>
          <CardDescription>
            Detect HOME/AWAY or team name labels in stream names and create separate channels per broadcast feed
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Master toggle */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Enable Feed Separation</Label>
              <p className="text-xs text-muted-foreground">
                When enabled, streams labeled HOME/AWAY or with team names are split into separate channels
              </p>
            </div>
            <Switch
              checked={feedSeparation.enabled}
              onCheckedChange={(checked) =>
                setFeedSeparation({ ...feedSeparation, enabled: checked })
              }
            />
          </div>

          {/* Nested options (only when enabled) */}
          {feedSeparation.enabled && (
            <div className="space-y-4 pl-2 border-l-2 border-muted ml-1">
              {/* Home terms */}
              <div className="space-y-1.5">
                <Label htmlFor="feed-home-terms">Home Feed Terms</Label>
                <Input
                  id="feed-home-terms"
                  value={feedSeparation.home_terms.join(", ")}
                  onChange={(e) =>
                    setFeedSeparation({
                      ...feedSeparation,
                      home_terms: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                    })
                  }
                  placeholder="HOME"
                />
                <p className="text-xs text-muted-foreground">
                  Comma-separated terms that indicate a home feed (e.g., HOME, Home Feed)
                </p>
              </div>

              {/* Away terms */}
              <div className="space-y-1.5">
                <Label htmlFor="feed-away-terms">Away Feed Terms</Label>
                <Input
                  id="feed-away-terms"
                  value={feedSeparation.away_terms.join(", ")}
                  onChange={(e) =>
                    setFeedSeparation({
                      ...feedSeparation,
                      away_terms: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
                    })
                  }
                  placeholder="AWAY"
                />
                <p className="text-xs text-muted-foreground">
                  Comma-separated terms that indicate an away feed (e.g., AWAY, Away Feed)
                </p>
              </div>

              {/* Detect team names toggle */}
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Detect Team Names</Label>
                  <p className="text-xs text-muted-foreground">
                    Also detect team names as feed indicators (e.g., &quot;Orioles Feed&quot; resolves to home team)
                  </p>
                </div>
                <Switch
                  checked={feedSeparation.detect_team_names}
                  onCheckedChange={(checked) =>
                    setFeedSeparation({ ...feedSeparation, detect_team_names: checked })
                  }
                />
              </div>

              {/* Label style */}
              <div className="space-y-1.5">
                <Label htmlFor="feed-label-style">Feed Label Style</Label>
                <Select
                  id="feed-label-style"
                  value={feedSeparation.label_style}
                  onChange={(e) =>
                    setFeedSeparation({
                      ...feedSeparation,
                      label_style: e.target.value as FeedSeparationSettings["label_style"],
                    })
                  }
                >
                  <option value="team_name">Team Name (e.g., &quot;Orioles Feed&quot;)</option>
                  <option value="short_name">Short Name (e.g., &quot;BAL Feed&quot;)</option>
                  <option value="home_away">Home/Away (e.g., &quot;Home Feed&quot;)</option>
                </Select>
                <p className="text-xs text-muted-foreground">
                  How feed labels appear in channel names
                </p>
              </div>
            </div>
          )}

          {/* Save button */}
          <Button
            onClick={() =>
              updateFeedSeparation.mutate(feedSeparation, {
                onSuccess: () => toast.success("Feed separation settings saved"),
                onError: () => toast.error("Failed to save feed separation settings"),
              })
            }
            disabled={updateFeedSeparation.isPending}
          >
            {updateFeedSeparation.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      </>
      )}

      {/* Channel Management Tab */}
      {activeTab === "channels" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Channel Management</h2>
        <p className="text-sm text-muted-foreground">Configure channel lifecycle, numbering, and sorting</p>
      </div>

      {/* Channel Lifecycle */}
      <Card>
        <CardHeader>
          <CardTitle>Channel Lifecycle</CardTitle>
          <CardDescription>
            Configure when channels are created and deleted for event groups
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="ch-create-timing">Channel Create Timing</Label>
              <Select
                id="ch-create-timing"
                value={lifecycle?.channel_create_timing ?? "same_day"}
                onChange={(e) =>
                  lifecycle && setLifecycle({ ...lifecycle, channel_create_timing: e.target.value })
                }
              >
                <option value="same_day">Same day</option>
                <option value="before_event">Before event + buffer</option>
              </Select>
              <Label htmlFor="ch-pre-buffer" className={lifecycle?.channel_create_timing !== "before_event" ? "text-muted-foreground" : ""}>
                Pre-Event Buffer (hours)
              </Label>
              <Input
                id="ch-pre-buffer"
                type="number"
                min={0}
                max={336}
                disabled={lifecycle?.channel_create_timing !== "before_event"}
                value={Math.round((lifecycle?.channel_pre_buffer_minutes ?? 60) / 60)}
                onChange={(e) => {
                  const val = parseInt(e.target.value)
                  if (!isNaN(val) && lifecycle) {
                    setLifecycle({ ...lifecycle, channel_pre_buffer_minutes: Math.max(0, Math.min(336, val)) * 60 })
                  }
                }}
              />
              <p className="text-xs text-muted-foreground">
                {lifecycle?.channel_create_timing === "before_event"
                  ? "Hours before event start to create channel"
                  : "\u00A0"}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ch-delete-timing">Channel Delete Timing</Label>
              <Select
                id="ch-delete-timing"
                value={lifecycle?.channel_delete_timing ?? "same_day"}
                onChange={(e) =>
                  lifecycle && setLifecycle({ ...lifecycle, channel_delete_timing: e.target.value })
                }
              >
                <option value="same_day">Same day</option>
                <option value="after_event">After event + buffer</option>
              </Select>
              <Label htmlFor="ch-post-buffer">Post-Event Buffer (hours)</Label>
              <Input
                id="ch-post-buffer"
                type="number"
                min={0}
                max={336}
                value={Math.round((lifecycle?.channel_post_buffer_minutes ?? 60) / 60)}
                onChange={(e) => {
                  const val = parseInt(e.target.value)
                  if (!isNaN(val) && lifecycle) {
                    setLifecycle({ ...lifecycle, channel_post_buffer_minutes: Math.max(0, Math.min(336, val)) * 60 })
                  }
                }}
              />
              <p className="text-xs text-muted-foreground">
                {lifecycle?.channel_delete_timing === "after_event"
                  ? "Hours after event ends to delete channel"
                  : "Midnight cross-over events will always use post-event buffer"}
              </p>
            </div>
          </div>

          <Button
            onClick={async () => {
              if (!lifecycle) return
              try {
                await updateLifecycle.mutateAsync(lifecycle)
                toast.success("Channel lifecycle settings saved")
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Failed to save")
              }
            }}
            disabled={updateLifecycle.isPending}
          >
            {updateLifecycle.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Channel Numbering & Consolidation */}
      <Card>
        <CardHeader>
          <CardTitle>Channel Numbering & Consolidation</CardTitle>
          <CardDescription>
            Configure how channel numbers are assigned, ordered, and how duplicate streams are handled
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Numbering Mode Toggle */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Numbering Mode</Label>
            <div className="grid grid-cols-2 gap-3">
              <label className={`flex flex-col p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                channelNumbering.global_channel_mode === "auto"
                  ? "border-primary bg-muted/30"
                  : "border-border hover:border-muted-foreground/50"
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <input type="radio" name="channel-mode" value="auto"
                    checked={channelNumbering.global_channel_mode === "auto"}
                    onChange={() => setChannelNumbering({
                      ...channelNumbering, global_channel_mode: "auto",
                    })}
                    className="accent-primary" />
                  <span className="font-medium text-sm">Auto</span>
                </div>
                <p className="text-xs text-muted-foreground leading-tight ml-5">
                  Sequential numbering from channel range start. Ordered by sport/league priority.
                </p>
              </label>
              <label className={`flex flex-col p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                channelNumbering.global_channel_mode === "manual"
                  ? "border-primary bg-muted/30"
                  : "border-border hover:border-muted-foreground/50"
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <input type="radio" name="channel-mode" value="manual"
                    checked={channelNumbering.global_channel_mode === "manual"}
                    onChange={() => setChannelNumbering({
                      ...channelNumbering, global_channel_mode: "manual",
                    })}
                    className="accent-primary" />
                  <span className="font-medium text-sm">Manual</span>
                </div>
                <p className="text-xs text-muted-foreground leading-tight ml-5">
                  Per-league starting channel numbers. Each league gets its own number range.
                </p>
              </label>
            </div>
          </div>

          {/* Channel Range (both modes) */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="ch-range-start-num">Channel Range Start</Label>
              <Input
                id="ch-range-start-num"
                type="number"
                min={1}
                value={channelRangeStart}
                onChange={(e) => setChannelRangeStart(e.target.value)}
                onBlur={(e) => {
                  if (!lifecycle) return
                  const val = parseInt(e.target.value)
                  if (!isNaN(val) && val >= 1) {
                    setChannelRangeStart(val.toString())
                    setLifecycle({ ...lifecycle, channel_range_start: val })
                  } else {
                    setChannelRangeStart(
                      lifecycle.channel_range_start?.toString() ?? "101"
                    )
                  }
                }}
              />
              <p className="text-xs text-muted-foreground">
                {channelNumbering.global_channel_mode === "auto"
                  ? "First channel number for all channels"
                  : "Default start for leagues without a configured start"}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ch-range-end-num">Channel Range End</Label>
              <Input
                id="ch-range-end-num"
                type="number"
                min={1}
                value={channelRangeEnd}
                onChange={(e) => setChannelRangeEnd(e.target.value)}
                onBlur={(e) => {
                  if (!lifecycle) return
                  if (e.target.value === "") {
                    setChannelRangeEnd("")
                    setLifecycle({ ...lifecycle, channel_range_end: null })
                  } else {
                    const val = parseInt(e.target.value)
                    if (!isNaN(val) && val >= 1) {
                      setChannelRangeEnd(val.toString())
                      setLifecycle({ ...lifecycle, channel_range_end: val })
                    } else {
                      setChannelRangeEnd(
                        lifecycle.channel_range_end?.toString() ?? ""
                      )
                    }
                  }
                }}
                placeholder="No limit"
              />
              <p className="text-xs text-muted-foreground">
                Last channel number (leave empty for no limit)
              </p>
            </div>
          </div>

          {/* Per-League Start Numbers (Manual mode only) */}
          {channelNumbering.global_channel_mode === "manual" && (
            <div className="space-y-3">
              <Label className="text-sm font-medium">
                Per-League Starting Channels
              </Label>
              <p className="text-xs text-muted-foreground">
                Set starting channel numbers for each league. Leagues without a
                configured start will use the channel range start.
              </p>
              {/* Search + subscribed-only filter */}
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Filter leagues..."
                    value={leagueSearch}
                    onChange={(e) => setLeagueSearch(e.target.value)}
                    className="pl-8 h-8"
                  />
                </div>
                <label className="flex items-center gap-2 cursor-pointer text-sm whitespace-nowrap">
                  <Switch
                    checked={showSubscribedOnly}
                    onCheckedChange={setShowSubscribedOnly}
                  />
                  Subscribed only
                </label>
              </div>
              <div className="border rounded-md max-h-64 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted sticky top-0">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Sport</th>
                      <th className="px-3 py-2 text-left font-medium">League</th>
                      <th className="px-3 py-2 text-right font-medium w-32">
                        Start Ch #
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {filteredLeagues.map((league) => (
                        <tr key={league.slug} className="hover:bg-muted/30">
                          <td className="px-3 py-1.5 text-muted-foreground">
                            {getSportDisplayName(league.sport, sportsMap)}
                          </td>
                          <td className="px-3 py-1.5">{league.name}</td>
                          <td className="px-3 py-1.5 text-right">
                            <Input
                              type="number"
                              min={1}
                              className="w-24 ml-auto text-right h-7 text-sm"
                              placeholder="—"
                              value={
                                channelNumbering.league_channel_starts[
                                  league.slug
                                ] ?? ""
                              }
                              onChange={(e) => {
                                const starts = {
                                  ...channelNumbering.league_channel_starts,
                                }
                                if (e.target.value === "") {
                                  delete starts[league.slug]
                                } else {
                                  const v = parseInt(e.target.value)
                                  if (!isNaN(v) && v >= 1) starts[league.slug] = v
                                }
                                setChannelNumbering({
                                  ...channelNumbering,
                                  league_channel_starts: starts,
                                })
                              }}
                            />
                          </td>
                        </tr>
                      ))}
                    {filteredLeagues.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-3 py-4 text-center text-muted-foreground">
                          {leagueSearch ? "No leagues match your search" : "No subscribed leagues"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Consolidation Mode */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Stream Consolidation</Label>
            <div className="grid grid-cols-2 gap-3">
              <label className={`flex flex-col p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                channelNumbering.global_consolidation_mode === "consolidate"
                  ? "border-primary bg-muted/30"
                  : "border-border hover:border-muted-foreground/50"
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <input type="radio" name="consolidation-mode"
                    value="consolidate"
                    checked={channelNumbering.global_consolidation_mode === "consolidate"}
                    onChange={() => setChannelNumbering({
                      ...channelNumbering,
                      global_consolidation_mode: "consolidate",
                    })}
                    className="accent-primary" />
                  <span className="font-medium text-sm">Consolidate</span>
                </div>
                <p className="text-xs text-muted-foreground leading-tight ml-5">
                  Merge multiple streams for the same event into one channel.
                  Exception keywords can override per-stream.
                </p>
              </label>
              <label className={`flex flex-col p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                channelNumbering.global_consolidation_mode === "separate"
                  ? "border-primary bg-muted/30"
                  : "border-border hover:border-muted-foreground/50"
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <input type="radio" name="consolidation-mode"
                    value="separate"
                    checked={channelNumbering.global_consolidation_mode === "separate"}
                    onChange={() => setChannelNumbering({
                      ...channelNumbering,
                      global_consolidation_mode: "separate",
                    })}
                    className="accent-primary" />
                  <span className="font-medium text-sm">Separate</span>
                </div>
                <p className="text-xs text-muted-foreground leading-tight ml-5">
                  Each stream gets its own channel. More channels, no merging.
                </p>
              </label>
            </div>
          </div>

          {/* Sort Priority Manager — always visible */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Channel Ordering</Label>
            <p className="text-xs text-muted-foreground">
              Channels are ordered by Sport → League → Event Time.
              Drag to reorder sport/league priority.
            </p>
            <SortPriorityManager
              currentSortBy="sport_league_time"
              showWhenSortBy="sport_league_time"
            />
          </div>

          <div className="pt-4 border-t">
            <Button
              onClick={handleSaveChannelNumbering}
              disabled={
                updateChannelNumbering.isPending || updateLifecycle.isPending
              }
            >
              {updateChannelNumbering.isPending || updateLifecycle.isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-1" />
              )}
              Save
            </Button>
            <p className="text-xs text-muted-foreground mt-2">
              Channel numbers will be updated on the next EPG generation.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Per-League Channel Config */}
      <Card>
        <CardHeader>
          <CardTitle>Per-League Channel Config</CardTitle>
          <CardDescription>
            Override channel profiles, channel group, and group mode per league. Leagues without overrides inherit global defaults.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Search + subscribed-only filter */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Filter leagues..."
                value={leagueSearch}
                onChange={(e) => setLeagueSearch(e.target.value)}
                className="pl-8 h-8"
              />
            </div>
            <label className="flex items-center gap-2 cursor-pointer text-sm whitespace-nowrap">
              <Switch
                checked={showSubscribedOnly}
                onCheckedChange={setShowSubscribedOnly}
              />
              Subscribed only
            </label>
          </div>
          <div className="border rounded-md max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted sticky top-0 z-10">
                <tr>
                  <th className="px-3 py-2 text-left font-medium w-8"></th>
                  <th className="px-3 py-2 text-left font-medium">Sport</th>
                  <th className="px-3 py-2 text-left font-medium">League</th>
                  <th className="px-3 py-2 text-left font-medium">Profiles</th>
                  <th className="px-3 py-2 text-left font-medium">Channel Group</th>
                  <th className="px-3 py-2 text-left font-medium">Group Mode</th>
                  <th className="px-3 py-2 text-right font-medium w-16"></th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {filteredLeagues.map((league) => {
                    const config = leagueConfigsData?.configs?.find(
                      (c) => c.league_code === league.slug
                    )
                    const isExpanded = expandedLeagueConfig === league.slug
                    const hasOverride = !!config
                    return (
                      <LeagueConfigRow
                        key={league.slug}
                        leagueName={league.name}
                        sportName={getSportDisplayName(league.sport, sportsMap)}
                        config={config ?? null}
                        isExpanded={isExpanded}
                        hasOverride={hasOverride}
                        channelProfiles={channelProfilesQuery.data ?? []}
                        channelGroups={channelGroupsQuery.data ?? []}
                        dispatcharrConnected={dispatcharrStatus.data?.connected ?? false}
                        onToggleExpand={() =>
                          setExpandedLeagueConfig(isExpanded ? null : league.slug)
                        }
                        onSave={async (data) => {
                          try {
                            await upsertLeagueConfigMutation.mutateAsync({
                              leagueCode: league.slug,
                              data,
                            })
                            toast.success(`Saved config for ${league.name}`)
                            setExpandedLeagueConfig(null)
                          } catch {
                            toast.error(`Failed to save config for ${league.name}`)
                          }
                        }}
                        onClear={async () => {
                          try {
                            await deleteLeagueConfigMutation.mutateAsync(league.slug)
                            toast.success(`Cleared config for ${league.name}`)
                          } catch {
                            toast.error(`Failed to clear config for ${league.name}`)
                          }
                        }}
                      />
                    )
                  })}
                {filteredLeagues.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-3 py-4 text-center text-muted-foreground">
                      {leagueSearch ? "No leagues match your search" : "No subscribed leagues"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Click a league row to expand and configure overrides. Changes apply on the next EPG generation.
          </p>
        </CardContent>
      </Card>

      {/* Stream Ordering */}
      <StreamOrderingManager />
      </>
      )}

      {/* EPG Generation Tab */}
      {activeTab === "epg" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">EPG Generation</h2>
        <p className="text-sm text-muted-foreground">Configure EPG output, scheduling, and game durations</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Output Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="epg-output-path">Output Path</Label>
              <Input
                id="epg-output-path"
                value={epg?.epg_output_path ?? "./teamarr.xml"}
                onChange={(e) => epg && setEPG({ ...epg, epg_output_path: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="epg-days-ahead">Output Days Ahead</Label>
              <Input
                id="epg-days-ahead"
                type="number"
                min={1}
                value={epg?.epg_output_days_ahead ?? 14}
                onChange={(e) =>
                  epg && setEPG({ ...epg, epg_output_days_ahead: parseInt(e.target.value) || 14 })
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="epg-lookback">EPG Start (Hours Ago)</Label>
              <Input
                id="epg-lookback"
                type="number"
                min={0}
                value={epg?.epg_lookback_hours ?? 6}
                onChange={(e) =>
                  epg && setEPG({ ...epg, epg_lookback_hours: parseInt(e.target.value) || 6 })
                }
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={epg?.include_final_events ?? false}
              onCheckedChange={(checked) =>
                epg && setEPG({ ...epg, include_final_events: checked })
              }
            />
            <Label>Include completed/final events in EPG</Label>
          </div>

          {/* Scheduled Generation */}
          <div className="space-y-4 pt-2 border-t">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Switch
                  checked={scheduler?.enabled ?? false}
                  onCheckedChange={(checked) =>
                    scheduler && setScheduler({ ...scheduler, enabled: checked })
                  }
                />
                <Label>Enable Scheduled Generation</Label>
              </div>
              <Badge variant={schedulerStatus.data?.running ? "success" : "secondary"}>
                {schedulerStatus.data?.running ? "Running" : "Stopped"}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cron-expression">Cron Expression</Label>
                <Input
                  id="cron-expression"
                  value={epg?.cron_expression ?? "0 * * * *"}
                  onChange={(e) => epg && setEPG({ ...epg, cron_expression: e.target.value })}
                  className="font-mono"
                  placeholder="0 * * * *"
                />
                <CronPreview expression={epg?.cron_expression ?? "0 * * * *"} />
              </div>
              <div className="space-y-2">
                <Label>Last Run</Label>
                <p className="text-sm text-muted-foreground pt-2">
                  {schedulerStatus.data?.last_run ?? "Never"}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 * * * *" })}
              >
                Every Hour
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 */2 * * *" })}
              >
                Every 2 Hours
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 */4 * * *" })}
              >
                Every 4 Hours
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 */6 * * *" })}
              >
                Every 6 Hours
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 0 * * *" })}
              >
                Daily at Midnight
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => epg && setEPG({ ...epg, cron_expression: "0 6 * * *" })}
              >
                Daily at 6 AM
              </Button>
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={handleTriggerRun} variant="outline" disabled={isGenerating}>
              {isGenerating ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <Play className="h-4 w-4 mr-1" />
              )}
              Run Now
            </Button>
            <Button
              onClick={handleSaveSchedulerSettings}
              disabled={updateEPG.isPending || updateScheduler.isPending}
            >
              {(updateEPG.isPending || updateScheduler.isPending) ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-1" />
              )}
              Save
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Default Durations</CardTitle>
          <CardDescription>Default event durations by sport (in hours)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {durations &&
              Object.entries(durations).map(([sport, hours]) => (
                <div key={sport} className="space-y-1">
                  <Label htmlFor={`duration-${sport}`}>
                    {getSportDisplayName(sport, sportsMap)}
                  </Label>
                  <Input
                    id={`duration-${sport}`}
                    type="number"
                    step="0.5"
                    min={0.5}
                    value={hours}
                    onChange={(e) =>
                      setDurations({
                        ...durations,
                        [sport]: parseFloat(e.target.value) || 3,
                      })
                    }
                  />
                </div>
              ))}
          </div>

          <Button onClick={handleSaveDurations} disabled={updateDurations.isPending}>
            {updateDurations.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Scheduled Channel Reset */}
      <Card>
        <CardHeader>
          <CardTitle>Scheduled Channel Reset</CardTitle>
          <CardDescription>
            For users experiencing stale channel logos in Jellyfin. Schedule a periodic
            purge of all Teamarr channels before your media server&apos;s guide refresh.
            Leave disabled if you&apos;re not having issues.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={scheduler?.channel_reset_enabled ?? false}
              onCheckedChange={(checked) =>
                scheduler && setScheduler({ ...scheduler, channel_reset_enabled: checked })
              }
            />
            <Label>Enable Scheduled Channel Reset</Label>
          </div>

          {scheduler?.channel_reset_enabled && (
            <>
              <div className="space-y-2">
                <Label htmlFor="reset-cron">Reset Schedule (Cron Expression)</Label>
                <Input
                  id="reset-cron"
                  value={scheduler?.channel_reset_cron ?? ""}
                  onChange={(e) =>
                    scheduler && setScheduler({ ...scheduler, channel_reset_cron: e.target.value })
                  }
                  className="font-mono"
                  placeholder="30 3 * * *"
                />
                <CronPreview expression={scheduler?.channel_reset_cron ?? ""} />
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    scheduler && setScheduler({ ...scheduler, channel_reset_cron: "30 2 * * *" })
                  }
                >
                  Daily 2:30 AM
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    scheduler && setScheduler({ ...scheduler, channel_reset_cron: "30 3 * * *" })
                  }
                >
                  Daily 3:30 AM
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    scheduler && setScheduler({ ...scheduler, channel_reset_cron: "30 4 * * *" })
                  }
                >
                  Daily 4:30 AM
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    scheduler && setScheduler({ ...scheduler, channel_reset_cron: "30 5 * * *" })
                  }
                >
                  Daily 5:30 AM
                </Button>
              </div>

              <p className="text-xs text-muted-foreground">
                Set this to run shortly before your media server&apos;s scheduled guide refresh.
                Channels will be recreated on the next EPG generation.
              </p>
            </>
          )}

          <Button
            onClick={async () => {
              if (!scheduler) return
              try {
                await updateScheduler.mutateAsync({
                  channel_reset_enabled: scheduler.channel_reset_enabled,
                  channel_reset_cron: scheduler.channel_reset_cron,
                })
                toast.success("Channel reset settings saved")
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Failed to save")
              }
            }}
            disabled={updateScheduler.isPending}
          >
            {updateScheduler.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>
      </>
      )}

      {/* Dispatcharr Tab */}
      {activeTab === "dispatcharr" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Dispatcharr Integration</h2>
        <p className="text-sm text-muted-foreground">Configure connection to Dispatcharr for channel management</p>
      </div>
      {/* Card 1: Connection Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Connection Settings</CardTitle>
              <CardDescription>Server URL and credentials</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleTestConnection} variant="outline" size="sm" disabled={testConnection.isPending}>
                {testConnection.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {dispatcharrStatus.data?.connected ? (
                <Badge variant="success" className="gap-1">
                  <CheckCircle className="h-3 w-3" /> Connected
                </Badge>
              ) : dispatcharrStatus.data?.configured && dispatcharrStatus.data?.error ? (
                <Badge variant="destructive" className="gap-1" title={dispatcharrStatus.data.error}>
                  <AlertTriangle className="h-3 w-3" /> Error
                </Badge>
              ) : dispatcharrStatus.data?.configured ? (
                <Badge variant="warning" className="gap-1">
                  <XCircle className="h-3 w-3" /> Disconnected
                </Badge>
              ) : (
                <Badge variant="secondary">Not Configured</Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Connection error banner */}
          {dispatcharrStatus.data?.configured && dispatcharrStatus.data?.error && (
            <div className="flex items-start gap-2 p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
              <AlertTriangle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
              <div className="text-sm">
                <p className="font-medium text-destructive">Connection Failed</p>
                <p className="text-muted-foreground">{dispatcharrStatus.data.error}</p>
              </div>
            </div>
          )}

          {/* Enable */}
          <div className="flex items-center gap-2">
            <Switch
              checked={dispatcharr.enabled ?? false}
              onCheckedChange={(checked) => setDispatcharr({ ...dispatcharr, enabled: checked })}
            />
            <Label>Enable Dispatcharr Integration</Label>
          </div>

          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="dispatcharr-url">URL</Label>
            <Input
              id="dispatcharr-url"
              value={dispatcharr.url ?? ""}
              onChange={(e) => setDispatcharr({ ...dispatcharr, url: e.target.value })}
              placeholder="http://localhost:9191"
            />
          </div>

          {/* Credentials */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="dispatcharr-username">Username</Label>
              <Input
                id="dispatcharr-username"
                value={dispatcharr.username ?? ""}
                onChange={(e) => setDispatcharr({ ...dispatcharr, username: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="dispatcharr-password">Password</Label>
              <Input
                id="dispatcharr-password"
                type="password"
                value={dispatcharr.password ?? ""}
                onChange={(e) => setDispatcharr({ ...dispatcharr, password: e.target.value })}
                placeholder="Leave blank to keep current"
              />
            </div>
          </div>

          {/* Save button */}
          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Card 2: EPG Source */}
      <Card>
        <CardHeader>
          <CardTitle>EPG Source</CardTitle>
          <CardDescription>Link channels to an EPG source in Dispatcharr</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="dispatcharr-epg">EPG Source</Label>
            <Select
              id="dispatcharr-epg"
              value={dispatcharr.epg_id?.toString() ?? ""}
              onChange={(e) =>
                setDispatcharr({
                  ...dispatcharr,
                  epg_id: e.target.value ? parseInt(e.target.value) : null,
                })
              }
              disabled={!dispatcharrStatus.data?.connected}
            >
              <option value="">Select EPG source...</option>
              {epgSourcesQuery.data?.sources?.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name} ({source.source_type})
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Associate Teamarr-managed channels with this EPG source in Dispatcharr.
            </p>
          </div>

          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Card 3: Default Channel Profiles */}
      <Card>
        <CardHeader>
          <CardTitle>Default Channel Profiles</CardTitle>
          <CardDescription>Profiles assigned to new channels</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <ChannelProfileSelector
              selectedIds={selectedProfileIds}
              onChange={setSelectedProfileIds}
              disabled={!dispatcharrStatus.data?.connected}
            />
            <p className="text-xs text-muted-foreground">
              These defaults apply to all groups unless overridden in individual group settings.
              Profile assignment is enforced on every EPG generation run.
            </p>
          </div>

          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Card 4: Default Stream Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Default Stream Profile</CardTitle>
          <CardDescription>Processing profile for channel streams</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <StreamProfileSelector
              value={dispatcharr.default_stream_profile_id ?? null}
              onChange={(id) => setDispatcharr({ ...dispatcharr, default_stream_profile_id: id })}
              disabled={!dispatcharrStatus.data?.connected}
              isGlobalDefault
            />
            <p className="text-xs text-muted-foreground">
              Stream profile defines how streams are processed (ffmpeg, VLC, proxy, etc).
              This default applies to all groups unless overridden.
            </p>
          </div>

          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Card 5: Default Channel Group */}
      <Card>
        <CardHeader>
          <CardTitle>Default Channel Group</CardTitle>
          <CardDescription>Default group and mode for event channels</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-sm font-medium">Channel Group</Label>
            <Select
              value={dispatcharr.default_channel_group_id?.toString() ?? ""}
              onChange={(e) => {
                const v = e.target.value
                setDispatcharr({
                  ...dispatcharr,
                  default_channel_group_id: v ? parseInt(v) : null,
                })
              }}
              disabled={!dispatcharrStatus.data?.connected}
              className="w-64"
            >
              <option value="">None</option>
              {(channelGroupsQuery.data ?? []).map((g) => (
                <option key={g.id} value={g.id.toString()}>
                  {g.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Static group used when mode is "Static". Per-league overrides take priority.
            </p>
            <div className="flex items-center gap-2 pt-1">
              <Switch
                id="include-m3u-groups"
                checked={includeM3uGroups}
                onCheckedChange={setIncludeM3uGroups}
                disabled={!dispatcharrStatus.data?.connected}
              />
              <Label htmlFor="include-m3u-groups" className="text-xs font-normal cursor-pointer">
                Show M3U-sourced channel groups
              </Label>
            </div>
            <p className="text-xs text-muted-foreground">
              Off by default. Enable to assign groups that originated from an M3U
              account (e.g., a group you manually curated that's also tagged with an M3U source).
            </p>
          </div>

          <div className="space-y-2">
            <Label className="text-sm font-medium">Group Mode</Label>
            <Select
              value={
                dispatcharr.default_channel_group_mode &&
                !["static", "sport", "league"].includes(dispatcharr.default_channel_group_mode)
                  ? "custom"
                  : dispatcharr.default_channel_group_mode ?? "static"
              }
              onChange={(e) => {
                const v = e.target.value
                if (v === "custom") {
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: "{sport} | {league}" })
                } else {
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: v || "static" })
                }
              }}
              className="w-64"
            >
              <option value="static">Static (use selected group)</option>
              <option value="sport">Dynamic by Sport</option>
              <option value="league">Dynamic by League</option>
              <option value="custom">Custom pattern</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              Static uses the group above. Dynamic modes auto-create groups named by sport or league.
              Custom lets you define a pattern with {"{sport}"} and {"{league}"} placeholders.
            </p>
          </div>

          {dispatcharr.default_channel_group_mode &&
            !["static", "sport", "league"].includes(dispatcharr.default_channel_group_mode) && (
            <div className="space-y-2">
              <Label className="text-sm font-medium">Custom Pattern</Label>
              <Input
                value={dispatcharr.default_channel_group_mode}
                onChange={(e) =>
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: e.target.value })
                }
                placeholder="{sport} | {league}"
                className="w-64"
              />
              <p className="text-xs text-muted-foreground">
                Use {"{sport}"} and {"{league}"} as placeholders. Example: "{"{sport}"} | {"{league}"}" creates groups like "Hockey | NHL".
              </p>
            </div>
          )}

          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Card 6: Logo Cleanup */}
      <Card>
        <CardHeader>
          <CardTitle>Logo Cleanup</CardTitle>
          <CardDescription>Remove unused logos from Dispatcharr</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Switch
                checked={dispatcharr.cleanup_unused_logos ?? false}
                onCheckedChange={(checked) => setDispatcharr({ ...dispatcharr, cleanup_unused_logos: checked })}
              />
              <Label>Clean up unused logos after generation</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              When enabled, removes <strong>all</strong> unused logos from Dispatcharr after EPG generation.
              This affects all unused logos, not just ones uploaded by Teamarr.
            </p>
          </div>

          <Button onClick={handleSaveDispatcharr} disabled={updateDispatcharr.isPending}>
            {updateDispatcharr.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      </>
      )}

      {/* Emby Tab */}
      {activeTab === "media-servers" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Media Servers</h2>
        <p className="text-sm text-muted-foreground">
          Auto-refresh Live TV guides after EPG generation. Both can be enabled at once.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Emby</CardTitle>
              <CardDescription>Auto-refresh Live TV guide after EPG generation</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleTestEmby} variant="outline" size="sm" disabled={testEmby.isPending}>
                {testEmby.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {embyTestResult && (
                embyTestResult.success ? (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle className="h-3 w-3" /> {embyTestResult.message}
                  </Badge>
                ) : (
                  <Badge variant="destructive" className="gap-1">
                    <XCircle className="h-3 w-3" /> {embyTestResult.message}
                  </Badge>
                )
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Enable */}
          <div className="flex items-center gap-2">
            <Switch
              checked={emby.enabled ?? false}
              onCheckedChange={(checked) => setEmby({ ...emby, enabled: checked })}
            />
            <Label>Enable Emby Integration</Label>
          </div>

          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="emby-url">URL</Label>
            <Input
              id="emby-url"
              value={emby.url ?? ""}
              onChange={(e) => setEmby({ ...emby, url: e.target.value })}
              placeholder="http://emby:8096"
            />
          </div>

          {/* API Key (preferred) */}
          <div className="space-y-2">
            <Label htmlFor="emby-api-key">API Key</Label>
            <Input
              id="emby-api-key"
              type="password"
              value={emby.api_key ?? ""}
              onChange={(e) => setEmby({ ...emby, api_key: e.target.value })}
              placeholder="Leave blank to keep current"
            />
            <p className="text-xs text-muted-foreground">
              Recommended. Generate in Emby Dashboard &rarr; API Keys. If set, username/password are ignored.
            </p>
          </div>

          {/* Username/Password (fallback) */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="emby-username">Username</Label>
              <Input
                id="emby-username"
                value={emby.username ?? ""}
                onChange={(e) => setEmby({ ...emby, username: e.target.value })}
                disabled={!!emby.api_key}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="emby-password">Password</Label>
              <Input
                id="emby-password"
                type="password"
                value={emby.password ?? ""}
                onChange={(e) => setEmby({ ...emby, password: e.target.value })}
                placeholder="Leave blank to keep current"
                disabled={!!emby.api_key}
              />
            </div>
          </div>

          {/* Save button */}
          <Button onClick={handleSaveEmby} disabled={updateEmby.isPending}>
            {updateEmby.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Jellyfin</CardTitle>
              <CardDescription>Auto-refresh Live TV guide after EPG generation</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleTestJellyfin} variant="outline" size="sm" disabled={testJellyfin.isPending}>
                {testJellyfin.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {jellyfinTestResult && (
                jellyfinTestResult.success ? (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle className="h-3 w-3" /> {jellyfinTestResult.message}
                  </Badge>
                ) : (
                  <Badge variant="destructive" className="gap-1">
                    <XCircle className="h-3 w-3" /> {jellyfinTestResult.message}
                  </Badge>
                )
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Enable */}
          <div className="flex items-center gap-2">
            <Switch
              checked={jellyfin.enabled ?? false}
              onCheckedChange={(checked) => setJellyfin({ ...jellyfin, enabled: checked })}
            />
            <Label>Enable Jellyfin Integration</Label>
          </div>

          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="jellyfin-url">URL</Label>
            <Input
              id="jellyfin-url"
              value={jellyfin.url ?? ""}
              onChange={(e) => setJellyfin({ ...jellyfin, url: e.target.value })}
              placeholder="http://jellyfin:8096"
            />
          </div>

          {/* API Key (preferred) */}
          <div className="space-y-2">
            <Label htmlFor="jellyfin-api-key">API Key</Label>
            <Input
              id="jellyfin-api-key"
              type="password"
              value={jellyfin.api_key ?? ""}
              onChange={(e) => setJellyfin({ ...jellyfin, api_key: e.target.value })}
              placeholder="Leave blank to keep current"
            />
            <p className="text-xs text-muted-foreground">
              Recommended. Generate in Jellyfin Dashboard &rarr; API Keys. If set, username/password are ignored.
            </p>
          </div>

          {/* Username/Password (fallback) */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="jellyfin-username">Username</Label>
              <Input
                id="jellyfin-username"
                value={jellyfin.username ?? ""}
                onChange={(e) => setJellyfin({ ...jellyfin, username: e.target.value })}
                disabled={!!jellyfin.api_key}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="jellyfin-password">Password</Label>
              <Input
                id="jellyfin-password"
                type="password"
                value={jellyfin.password ?? ""}
                onChange={(e) => setJellyfin({ ...jellyfin, password: e.target.value })}
                placeholder="Leave blank to keep current"
                disabled={!!jellyfin.api_key}
              />
            </div>
          </div>

          {/* Save button */}
          <Button onClick={handleSaveJellyfin} disabled={updateJellyfin.isPending}>
            {updateJellyfin.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>
      </>
      )}

      {/* Advanced Tab */}
      {activeTab === "advanced" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Advanced</h2>
        <p className="text-sm text-muted-foreground">Advanced configuration options</p>
      </div>

      {/* Update Notifications */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Update Notifications</CardTitle>
              <CardDescription>Check for new versions of Teamarr</CardDescription>
            </div>
            {updateInfoQuery.data?.update_available && (
              <Badge variant="warning">Update Available</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Current Version and Update Status */}
          <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
            <div>
              <p className="text-sm font-medium">
                Current Version: {updateInfoQuery.data?.current_version ?? "Loading..."}
              </p>
              {updateInfoQuery.data?.update_available && updateInfoQuery.data?.latest_version && (
                <p className="text-sm text-muted-foreground">
                  Latest: {updateInfoQuery.data.latest_version}
                  {updateInfoQuery.data.build_type === "dev" && " (dev)"}
                  {updateInfoQuery.data.latest_date && (
                    <span className="ml-2 text-xs">
                      ({formatDateTime(updateInfoQuery.data.latest_date)})
                    </span>
                  )}
                </p>
              )}
              {!updateInfoQuery.data?.update_available && updateInfoQuery.data?.latest_date && (
                <p className="text-xs text-muted-foreground">
                  Released: {formatDateTime(updateInfoQuery.data.latest_date)}
                </p>
              )}
              {updateInfoQuery.data?.checked_at && (
                <p className="text-xs text-muted-foreground">
                  Last checked: {formatRelativeTime(updateInfoQuery.data.checked_at)}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              {updateInfoQuery.data?.update_available && updateInfoQuery.data?.download_url && (
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => window.open(updateInfoQuery.data!.download_url!, "_blank")}
                >
                  <ExternalLink className="h-4 w-4 mr-1" />
                  View Update
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => forceCheckUpdates.mutate()}
                disabled={forceCheckUpdates.isPending}
              >
                {forceCheckUpdates.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-1" />
                )}
                Check Now
              </Button>
            </div>
          </div>

          {/* Update Check Settings */}
          <div className="space-y-4 pt-2 border-t">
            <div className="flex items-center gap-2">
              <Switch
                checked={updateCheck.enabled}
                onCheckedChange={(checked) => setUpdateCheck({ ...updateCheck, enabled: checked })}
              />
              <Label>Enable Automatic Update Checks</Label>
            </div>

            {updateCheck.enabled && (
              <>
                <div className="flex items-center gap-4 pl-6">
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={updateCheck.notify_stable}
                      onCheckedChange={(checked) =>
                        setUpdateCheck({ ...updateCheck, notify_stable: checked })
                      }
                    />
                    <Label className="text-sm">Notify about stable releases</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={updateCheck.notify_dev}
                      onCheckedChange={(checked) =>
                        setUpdateCheck({ ...updateCheck, notify_dev: checked })
                      }
                    />
                    <Label className="text-sm">Notify about dev builds</Label>
                  </div>
                </div>
              </>
            )}
          </div>

          <Button
            onClick={() => {
              updateUpdateCheck.mutate(updateCheck, {
                onSuccess: () => toast.success("Update check settings saved"),
                onError: () => toast.error("Failed to save update check settings"),
              })
            }}
            disabled={updateUpdateCheck.isPending}
          >
            {updateUpdateCheck.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* Backup & Restore */}
      <BackupRestoreCard />

      {/* Data Caches */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Database className="h-5 w-5" />
                Data Caches
              </CardTitle>
              <CardDescription>Team/league directory and cached game data from providers</CardDescription>
            </div>
            {cacheStatus?.is_stale && (
              <Badge variant="warning">Directory Stale</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 lg:divide-x">
            {/* Team & League Directory Section */}
            <div className="flex flex-col gap-4 lg:pr-6">
              <h4 className="text-sm font-medium">Team & League Directory</h4>
              <div className="grid grid-cols-2 gap-3">
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
              <h4 className="text-sm font-medium">Game Data Cache</h4>
              <div className="grid grid-cols-2 gap-3">
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
              <h4 className="text-sm font-medium">Stream Match Cache</h4>
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
              <h4 className="text-sm font-medium">Run History</h4>
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

      {/* TheSportsDB API Key */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>TheSportsDB API Key</CardTitle>
            <Badge variant={display?.tsdb_api_key && display.tsdb_api_key.length > 3 ? "default" : "secondary"} className="text-xs">
              {display?.tsdb_api_key && display.tsdb_api_key.length > 3 ? "Premium" : "Free Tier"}
            </Badge>
          </div>
          <CardDescription>Optional premium API key for full event coverage and higher rate limits</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="tsdb-api-key">API Key</Label>
            <div className="flex gap-2">
              <Input
                id="tsdb-api-key"
                type="password"
                value={display?.tsdb_api_key ?? ""}
                onChange={(e) => {
                  display && setDisplay({ ...display, tsdb_api_key: e.target.value })
                  setTsdbValidation(null)
                }}
                placeholder="Leave blank to use free tier"
                className="flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                disabled={tsdbValidating || !display?.tsdb_api_key}
                onClick={async () => {
                  if (!display?.tsdb_api_key) return
                  setTsdbValidating(true)
                  setTsdbValidation(null)
                  try {
                    const result = await validateTSDBKey(display.tsdb_api_key)
                    setTsdbValidation(result)
                  } catch {
                    setTsdbValidation({ valid: false, is_premium: false, message: "Connection error" })
                  } finally {
                    setTsdbValidating(false)
                  }
                }}
              >
                {tsdbValidating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Validate"}
              </Button>
            </div>
            {tsdbValidation && (
              <p className={`text-xs ${tsdbValidation.valid ? (tsdbValidation.is_premium ? "text-green-500" : "text-yellow-500") : "text-red-500"}`}>
                {tsdbValidation.message}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Premium key ($9/mo) unlocks full event coverage for leagues like Svenska Cupen, plus 100 req/min (vs 30 free).
              Get a key at <a href="https://www.thesportsdb.com/pricing" target="_blank" rel="noopener noreferrer" className="underline">thesportsdb.com/pricing</a>
            </p>
          </div>

          <Button onClick={() => handleSaveDisplay("TSDB API key saved")} disabled={updateDisplay.isPending}>
            {updateDisplay.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>

      {/* XMLTV Generator Metadata */}
      <Card>
        <CardHeader>
          <CardTitle>XMLTV Generator Metadata</CardTitle>
          <CardDescription>Customize XMLTV output file metadata</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="xmltv-name">XMLTV Generator Name</Label>
              <Input
                id="xmltv-name"
                value={display?.xmltv_generator_name ?? "Teamarr"}
                onChange={(e) => display && setDisplay({ ...display, xmltv_generator_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="xmltv-url">XMLTV Generator URL</Label>
              <Input
                id="xmltv-url"
                value={display?.xmltv_generator_url ?? "https://github.com/Pharaoh-Labs/teamarr"}
                onChange={(e) => display && setDisplay({ ...display, xmltv_generator_url: e.target.value })}
                placeholder="https://github.com/Pharaoh-Labs/teamarr"
              />
            </div>
          </div>

          <Button onClick={() => handleSaveDisplay("XMLTV metadata saved")} disabled={updateDisplay.isPending}>
            {updateDisplay.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </CardContent>
      </Card>
      </>
      )}


      </div>
    </div>
  )
}
