import { useState, useEffect, useRef } from "react"
import { toast } from "sonner"
import {
  Loader2,
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
  RefreshCw,
  ExternalLink,
  Shield,
  ShieldOff,
  HardDrive,
} from "lucide-react"
import {
  profileIdsToApi,
  apiToProfileIds,
} from "@/components/ChannelProfileSelector"
import { useGenerationProgress } from "@/contexts/GenerationContext"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { ToggleCard } from "@/components/ui/toggle-card"
import { Badge } from "@/components/ui/badge"
import { SubNav } from "@/components/ui/sub-nav"
import { CronPreview } from "@/components/CronPreview"
import { ScheduledChannelResetCard } from "@/components/ScheduledChannelResetCard"
import {
  useSettings,
  useUpdateDispatcharrSettings,
  useTestDispatcharrConnection,
  useDispatcharrStatus,
  useDispatcharrEPGSources,
  useUpdateSchedulerSettings,
  useSchedulerStatus,
  useUpdateEPGSettings,
  useUpdateDisplaySettings,
  useUpdateCheckSettings,
  useUpdateUpdateCheckSettings,
  useCheckForUpdates,
  useForceCheckForUpdates,
  useEmbySettings,
  useUpdateEmbySettings,
  useTestEmbyConnection,
  useJellyfinSettings,
  useUpdateJellyfinSettings,
  useTestJellyfinConnection,
  useChannelsDVRSettings,
  useUpdateChannelsDVRSettings,
  useTestChannelsDVRConnection,
  useChannelsDVRSources,
  useChannelsDVRLineups,
} from "@/hooks/useSettings"
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
  SchedulerSettings,
  EPGSettings,
  DisplaySettings,
  UpdateCheckSettings,
  EmbySettings,
  JellyfinSettings,
  ChannelsDVRSettings,
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
  // Which backup is selected in the compact file dropdown
  const [selectedBackup, setSelectedBackup] = useState<string>("")

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

  // Keep the dropdown selection valid: default to the newest backup, and
  // re-point if the currently selected file was deleted/rotated away.
  useEffect(() => {
    const files = backupsData?.backups ?? []
    if (!files.length) {
      if (selectedBackup) setSelectedBackup("")
      return
    }
    if (!files.some((b) => b.filename === selectedBackup)) {
      setSelectedBackup(files[0].filename)
    }
  }, [backupsData, selectedBackup])

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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

            <SaveButton
              onClick={handleSaveSettings}
              pending={updateSettings.isPending}
              disabled={!hasChanges}
              size="sm"
            >
              Save Settings
            </SaveButton>
          </div>
        </div>

        {/* Backup Files Section */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium border-b pb-2">Backup Files</h4>

          {backupsLoading ? (
            <div className="flex justify-center py-3">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : !backupsData?.backups.length ? (
            <p className="text-sm text-muted-foreground">
              No backups yet — use “Create Backup” above.
            </p>
          ) : (() => {
            const selected = backupsData.backups.find((b) => b.filename === selectedBackup)
            return (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Select
                    value={selectedBackup}
                    onChange={(e) => setSelectedBackup(e.target.value)}
                    className="flex-1 font-mono text-xs"
                  >
                    {backupsData.backups.map((backup) => (
                      <option key={backup.filename} value={backup.filename}>
                        {backup.is_protected ? "🔒 " : ""}{backup.filename} · {formatBytes(backup.size_bytes)} · {formatDate(backup.created_at)}
                      </option>
                    ))}
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0"
                    onClick={() => selected && downloadSpecificBackup(selected.filename)}
                    disabled={!selected}
                    title="Download"
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0"
                    onClick={() => selected && handleRestoreFromFile(selected.filename)}
                    disabled={!selected || restoringFile === selected?.filename}
                    title="Restore"
                  >
                    {restoringFile === selected?.filename ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Upload className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0"
                    onClick={() => selected && handleToggleProtection(selected.filename, selected.is_protected)}
                    disabled={!selected}
                    title={selected?.is_protected ? "Unprotect" : "Protect"}
                  >
                    {selected?.is_protected ? (
                      <ShieldOff className="h-4 w-4" />
                    ) : (
                      <Shield className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9 shrink-0 text-destructive hover:text-destructive"
                    onClick={() => selected && handleDelete(selected.filename)}
                    disabled={!selected || deletingFile === selected?.filename || selected?.is_protected}
                    title={selected?.is_protected ? "Cannot delete protected backup" : "Delete"}
                  >
                    {deletingFile === selected?.filename ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                {selected && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant={selected.backup_type === "scheduled" ? "secondary" : "outline"}>
                      {selected.backup_type}
                    </Badge>
                    {selected.is_protected && (
                      <span className="inline-flex items-center gap-1 text-amber-500">
                        <Shield className="h-3 w-3" /> Protected
                      </span>
                    )}
                    <span>{backupsData.backups.length} backup{backupsData.backups.length === 1 ? "" : "s"} total</span>
                  </div>
                )}
              </div>
            )
          })()}
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
        <Alert
          variant="warning"
          icon={<AlertTriangle className="h-4 w-4 text-amber-500" />}
          title="Important"
        >
          <p className="text-xs">
            Restoring a backup will replace ALL current data. The application needs to be restarted for changes to take effect.
            Protected backups (<Shield className="h-3 w-3 inline" />) are excluded from automatic rotation.
          </p>
        </Alert>
      </CardContent>
    </Card>
  )
}

// Per-League Config Row Component

type SettingsTab = "general" | "teams" | "events" | "channels" | "dispatcharr" | "media-servers" | "advanced"

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "dispatcharr", label: "Dispatcharr" },
  { id: "media-servers", label: "Media Servers" },
  { id: "advanced", label: "Advanced" },
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
  const updateScheduler = useUpdateSchedulerSettings()
  const updateEPG = useUpdateEPGSettings()
  const updateDisplay = useUpdateDisplaySettings()

  // Feed separation settings

  // Emby settings
  const { data: embyData } = useEmbySettings()
  const updateEmby = useUpdateEmbySettings()
  const testEmby = useTestEmbyConnection()

  // Jellyfin settings
  const { data: jellyfinData } = useJellyfinSettings()
  const updateJellyfin = useUpdateJellyfinSettings()
  const testJellyfin = useTestJellyfinConnection()

  // Channels DVR settings
  const { data: channelsdvrData } = useChannelsDVRSettings()
  const updateChannelsDVR = useUpdateChannelsDVRSettings()
  const testChannelsDVR = useTestChannelsDVRConnection()
  const [channelsdvr, setChannelsDVR] = useState<Partial<ChannelsDVRSettings>>({
    enabled: false,
    url: null,
    source_name: null,
  })
  const [channelsdvrTestResult, setChannelsDVRTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const { data: channelsdvrSourcesData, isFetching: channelsdvrSourcesLoading } =
    useChannelsDVRSources(channelsdvr.url || channelsdvrData?.url)
  const { data: channelsdvrLineupsData, isFetching: channelsdvrLineupsLoading } =
    useChannelsDVRLineups(channelsdvr.url || channelsdvrData?.url)

  // Update check settings
  const { data: updateCheckData } = useUpdateCheckSettings()
  const updateUpdateCheck = useUpdateUpdateCheckSettings()
  const updateInfoQuery = useCheckForUpdates(updateCheckData?.enabled ?? true)
  const forceCheckUpdates = useForceCheckForUpdates()
  const { formatDateTime } = useDateFormat()

  // Local form state
  const [dispatcharr, setDispatcharr] = useState<Partial<DispatcharrSettings>>({})
  const [scheduler, setScheduler] = useState<SchedulerSettings | null>(null)
  const [epg, setEPG] = useState<EPGSettings | null>(null)
  const [display, setDisplay] = useState<DisplaySettings | null>(null)
  const [tsdbValidation, setTsdbValidation] = useState<TSDBKeyValidationResult | null>(null)
  const [tsdbValidating, setTsdbValidating] = useState(false)
  const [updateCheck, setUpdateCheck] = useState<UpdateCheckSettings>({
    enabled: true,
    notify_stable: true,
    notify_dev: true,
    github_owner: "Pharaoh-Labs",
    github_repo: "teamarr",
    dev_branch: "dev",
    auto_detect_branch: true,
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

  // Selected profile IDs for display (converted from API format)
  const [selectedProfileIds, setSelectedProfileIds] = useState<(number | string)[]>([])

  // Default channel-group selection (with M3U filtering) moved to the Channels
  // page (DispatcharrOutputSettings) in the v2.7.0 IA overhaul.

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
      setScheduler(settings.scheduler)
      setEPG(settings.epg)
      if (settings.display) {
        setDisplay(settings.display)
      }
    }
  }, [settings])

  // Sync update check state when data loads
  useEffect(() => {
    if (updateCheckData) {
      setUpdateCheck(updateCheckData)
    }
  }, [updateCheckData])


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

  // Sync channels dvr state when data loads
  useEffect(() => {
    if (channelsdvrData) {
      setChannelsDVR({
        enabled: channelsdvrData.enabled,
        url: channelsdvrData.url,
        source_name: channelsdvrData.source_name,
        lineup_id: channelsdvrData.lineup_id,
      })
    }
  }, [channelsdvrData])

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

  const handleSaveChannelsDVR = async () => {
    try {
      const data: Partial<ChannelsDVRSettings> = {
        enabled: channelsdvr.enabled,
        url: channelsdvr.url,
        source_name: channelsdvr.source_name,
        lineup_id: channelsdvr.lineup_id,
      }
      await updateChannelsDVR.mutateAsync(data)
      toast.success("Channels DVR settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTestChannelsDVR = async () => {
    try {
      setChannelsDVRTestResult(null)
      const result = await testChannelsDVR.mutateAsync({
        url: channelsdvr.url || undefined,
        source_name: channelsdvr.source_name || undefined,
      })
      if (result.success) {
        const versionPart = result.server_version ? ` (v${result.server_version})` : ""
        const sourcePart = result.source_name ? ` — source '${result.source_name}' OK` : ""
        setChannelsDVRTestResult({
          success: true,
          message: `Connected to Channels DVR${versionPart}${sourcePart}`,
        })
      } else {
        setChannelsDVRTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setChannelsDVRTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      })
    }
  }

  const handleTriggerRun = () => {
    // Use the same streaming endpoint as "Generate EPG" - full workflow with progress
    startGeneration()
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
      </div>

      {/* Tab Navigation */}
      <SubNav
        items={TABS.map((t) => ({ key: t.id, label: t.label }))}
        value={activeTab}
        onChange={(k) => setActiveTab(k as SettingsTab)}
      />

      {/* Tab Content */}
      <div className="space-y-3 min-h-[400px]">

      {/* General Tab */}
      {activeTab === "general" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">General Settings</h2>
      </div>

      {/* Tile 1: Time/Localization Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Time/Localization Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Explainer: the two timezones */}
          <Alert variant="info" title="Teamarr uses two timezones">
            <ul className="list-disc list-inside space-y-0.5">
              <li><strong>UI Display</strong> — how times appear in this interface. Set by the <code>TZ</code> environment variable.</li>
              <li><strong>EPG Output</strong> — the timezone written into generated EPG/XMLTV and template variables like {"{game_time}"}.</li>
            </ul>
            <p className="mt-1">
              These can differ — e.g. browse in your local time while your media server expects EPG in its own timezone.
            </p>
          </Alert>

          {/* Subsection: Timezones (side by side) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="ui-timezone" className="text-sm font-semibold">UI Display Timezone</Label>
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
              <Label htmlFor="epg-timezone" className="text-sm font-semibold">EPG Output Timezone</Label>
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

          {/* Subsection: Time Formatting (side by side) */}
          <div className="space-y-3">
            <Label className="text-sm font-semibold">Time Formatting</Label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
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
                  <Label className="font-normal">Show Timezone Abbreviation</Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  Applies to UI display and EPG output
                </p>
              </div>
            </div>
          </div>

          <SaveButton
            onClick={handleSaveEPGAndDisplay}
            pending={updateDisplay.isPending || updateEPG.isPending}
          />
        </CardContent>
      </Card>

      {/* Tile 2: Schedule */}
      <Card>
        <CardHeader>
          <CardTitle>Schedule</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-4">
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
            <SaveButton
              onClick={handleSaveSchedulerSettings}
              pending={updateEPG.isPending || updateScheduler.isPending}
            />
          </div>
        </CardContent>
      </Card>

      {/* Tile 3: TheSportsDB API Key */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>TheSportsDB API Key</CardTitle>
            <Badge variant={display?.tsdb_api_key && display.tsdb_api_key.length > 3 ? "default" : "secondary"} className="text-xs">
              {display?.tsdb_api_key && display.tsdb_api_key.length > 3 ? "Premium" : "Free Tier"}
            </Badge>
          </div>
          <CardDescription>
            Optional premium key for TSDB league coverage, adding custom leagues, and higher rate limits — get one at{" "}
            <a href="https://www.thesportsdb.com/pricing" target="_blank" rel="noopener noreferrer" className="underline">thesportsdb.com/pricing</a>
          </CardDescription>
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
          </div>

          <SaveButton onClick={() => handleSaveDisplay("TSDB API key saved")} pending={updateDisplay.isPending} />
        </CardContent>
      </Card>

      {/* Update Notifications — first adopter of the ToggleCard primitive */}
      <ToggleCard
        title="Update Notifications"
        enabled={updateCheck.enabled}
        onEnabledChange={(checked) => setUpdateCheck({ ...updateCheck, enabled: checked })}
        headerExtra={
          updateInfoQuery.data?.update_available ? (
            <Badge variant="warning">Update Available</Badge>
          ) : undefined
        }
        always={
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
        }
        footer={
          <SaveButton
            onClick={() => {
              updateUpdateCheck.mutate(updateCheck, {
                onSuccess: () => toast.success("Update check settings saved"),
                onError: () => toast.error("Failed to save update check settings"),
              })
            }}
            pending={updateUpdateCheck.isPending}
          />
        }
      >
        {/* Notification preferences — revealed by the header toggle */}
        <div className="space-y-3 pt-2 border-t">
          <Label className="text-sm text-muted-foreground">Notify me about</Label>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Switch
                checked={updateCheck.notify_stable}
                onCheckedChange={(checked) =>
                  setUpdateCheck({ ...updateCheck, notify_stable: checked })
                }
              />
              <Label className="text-sm">Stable releases</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={updateCheck.notify_dev}
                onCheckedChange={(checked) =>
                  setUpdateCheck({ ...updateCheck, notify_dev: checked })
                }
              />
              <Label className="text-sm">Dev builds</Label>
            </div>
          </div>
        </div>
      </ToggleCard>
      </>
      )}

      {/* Teams Tab */}

      {/* Event Groups Tab */}

      {/* Channel Management Tab */}


      {/* Dispatcharr Tab */}
      {activeTab === "dispatcharr" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Dispatcharr Integration</h2>
      </div>
      {/* Card 1: Connection Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Connection Settings</CardTitle>
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
            <Alert
              variant="destructive"
              icon={<AlertTriangle className="h-4 w-4 text-destructive" />}
              title="Connection Failed"
            >
              <p className="text-muted-foreground">{dispatcharrStatus.data.error}</p>
            </Alert>
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
        </CardContent>
      </Card>

      {/* Card 2: EPG Source */}
      <Card>
        <CardHeader>
          <CardTitle>EPG Source</CardTitle>
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

          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
        </CardContent>
      </Card>

      {/* Card 3: Logo Cleanup — a Dispatcharr-instance housekeeping behavior, so
          it lives with the connection/EPG-source config. (Default profiles,
          channel group, and group mode moved to Channels → Dispatcharr Output in
          the v2.7.0 IA overhaul; logo cleanup is maintenance, not channel routing.) */}
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
                onCheckedChange={(checked) =>
                  setDispatcharr({ ...dispatcharr, cleanup_unused_logos: checked })
                }
              />
              <Label>Clean up unused logos after generation</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              When enabled, removes <strong>all</strong> unused logos from Dispatcharr after EPG generation.
              This affects all unused logos, not just ones uploaded by Teamarr.
            </p>
          </div>

          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
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
          Connect media servers to auto-refresh their live TV guides after EPG generation.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Emby</CardTitle>
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <SaveButton onClick={handleSaveEmby} pending={updateEmby.isPending} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Jellyfin</CardTitle>
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <SaveButton onClick={handleSaveJellyfin} pending={updateJellyfin.isPending} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Channels DVR</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleTestChannelsDVR} variant="outline" size="sm" disabled={testChannelsDVR.isPending}>
                {testChannelsDVR.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {channelsdvrTestResult && (
                channelsdvrTestResult.success ? (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle className="h-3 w-3" /> {channelsdvrTestResult.message}
                  </Badge>
                ) : (
                  <Badge variant="destructive" className="gap-1">
                    <XCircle className="h-3 w-3" /> {channelsdvrTestResult.message}
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
              checked={channelsdvr.enabled ?? false}
              onCheckedChange={(checked) => setChannelsDVR({ ...channelsdvr, enabled: checked })}
            />
            <Label>Enable Channels DVR Integration</Label>
          </div>

          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="channelsdvr-url">URL</Label>
            <Input
              id="channelsdvr-url"
              value={channelsdvr.url ?? ""}
              onChange={(e) => setChannelsDVR({ ...channelsdvr, url: e.target.value })}
              placeholder="http://channelsdvr:8089"
            />
          </div>

          {/* Source Name (discovered list) */}
          <div className="space-y-2">
            <Label htmlFor="channelsdvr-source-name">M3U Source</Label>
            {(() => {
              const sources = channelsdvrSourcesData?.sources ?? []
              const sourcesError = channelsdvrSourcesData && !channelsdvrSourcesData.success
                ? channelsdvrSourcesData.error : null
              const saved = channelsdvr.source_name ?? ""
              const savedMissing = saved && sources.length > 0 && !sources.includes(saved)
              const noUrl = !channelsdvr.url
              return (
                <>
                  <Select
                    id="channelsdvr-source-name"
                    value={saved}
                    onChange={(e) => setChannelsDVR({ ...channelsdvr, source_name: e.target.value })}
                    disabled={noUrl || channelsdvrSourcesLoading}
                  >
                    <option value="">
                      {noUrl
                        ? "— Set URL first —"
                        : channelsdvrSourcesLoading
                        ? "Loading sources…"
                        : sources.length === 0
                        ? "— No sources discovered —"
                        : "— Select an M3U source —"}
                    </option>
                    {sources.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                    {savedMissing && (
                      <option value={saved}>{saved} (not found on server)</option>
                    )}
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Discovered from <code className="px-1 rounded bg-muted">GET /devices</code> (Provider = m3u).
                    Refresh hits <code className="px-1 rounded bg-muted">POST /providers/m3u/sources/&lt;name&gt;/refresh</code> after each generation.
                  </p>
                  {sourcesError && (
                    <p className="text-xs text-destructive">Couldn't load sources: {sourcesError}</p>
                  )}
                </>
              )
            })()}
          </div>

          {/* XMLTV Lineup (drives EPG refresh) */}
          <div className="space-y-2">
            <Label htmlFor="channelsdvr-lineup-id">XMLTV Lineup (EPG)</Label>
            {(() => {
              const lineups = channelsdvrLineupsData?.lineups ?? []
              const lineupsError = channelsdvrLineupsData && !channelsdvrLineupsData.success
                ? channelsdvrLineupsData.error : null
              const saved = channelsdvr.lineup_id ?? ""
              const savedMissing = saved && lineups.length > 0 && !lineups.some((l) => l.id === saved)
              const noUrl = !channelsdvr.url
              return (
                <>
                  <Select
                    id="channelsdvr-lineup-id"
                    value={saved}
                    onChange={(e) => setChannelsDVR({ ...channelsdvr, lineup_id: e.target.value })}
                    disabled={noUrl || channelsdvrLineupsLoading}
                  >
                    <option value="">
                      {noUrl
                        ? "— Set URL first —"
                        : channelsdvrLineupsLoading
                        ? "Loading lineups…"
                        : lineups.length === 0
                        ? "— No lineups discovered —"
                        : "— Select an XMLTV lineup —"}
                    </option>
                    {lineups.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name === l.id ? l.id : `${l.name} (${l.id})`}
                      </option>
                    ))}
                    {savedMissing && (
                      <option value={saved}>{saved} (not found on server)</option>
                    )}
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Discovered from <code className="px-1 rounded bg-muted">GET /dvr/lineups</code>.
                    Refresh hits <code className="px-1 rounded bg-muted">PUT /dvr/lineups/&lt;id&gt;</code> so the EPG actually updates.
                    Without this the M3U refresh leaves the guide stale.
                  </p>
                  {lineupsError && (
                    <p className="text-xs text-destructive">Couldn't load lineups: {lineupsError}</p>
                  )}
                </>
              )
            })()}
          </div>

          {/* Save button */}
          <SaveButton onClick={handleSaveChannelsDVR} pending={updateChannelsDVR.isPending} />
        </CardContent>
      </Card>

      <ScheduledChannelResetCard />
      </>
      )}

      {/* Advanced Tab */}
      {activeTab === "advanced" && (
      <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Advanced</h2>
      </div>

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

      </>
      )}


      </div>
    </div>
  )
}
