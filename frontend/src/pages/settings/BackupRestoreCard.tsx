import { useState, useRef } from "react"
import { toast } from "sonner"
import {
  Loader2,
  AlertTriangle,
  Plus,
  Trash2,
  Download,
  Upload,
  Shield,
  ShieldOff,
  HardDrive,
} from "lucide-react"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { CronPreview } from "@/components/CronPreview"
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
import { formatBytes } from "./format"

interface BackupScheduleSettings {
  enabled: boolean
  cron: string
  max_count: number
}

const PRESETS = [
  { label: "Daily 3 AM", cron: "0 3 * * *" },
  { label: "Weekly (Sun)", cron: "0 3 * * 0" },
  { label: "Monthly (1st)", cron: "0 3 1 * *" },
]

function ScheduledBackupsSection({ initial }: { initial: BackupScheduleSettings }) {
  const updateSettings = useUpdateBackupSettings()
  const [localSettings, setLocalSettings] = useState<BackupScheduleSettings>({
    enabled: initial.enabled,
    cron: initial.cron,
    max_count: initial.max_count,
  })
  const [hasChanges, setHasChanges] = useState(false)

  const handleSaveSettings = async () => {
    try {
      await updateSettings.mutateAsync(localSettings)
      toast.success("Backup settings saved")
      setHasChanges(false)
    } catch {
      toast.error("Failed to save backup settings")
    }
  }

  return (
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
            {PRESETS.map((preset) => (
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
  )
}

export function BackupRestoreCard() {
  const { data: settings } = useBackupSettings()

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

  // Keep the dropdown selection valid: default to the newest backup, and
  // re-point if the currently selected file was deleted/rotated away.
  const files = backupsData?.backups ?? []
  const effectiveSelected = files.some((b) => b.filename === selectedBackup)
    ? selectedBackup
    : files[0]?.filename ?? ""

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
        {settings && <ScheduledBackupsSection initial={settings} />}

        {/* Backup Files Section */}
        <div className="space-y-2">
          <h4 className="text-sm font-medium border-b pb-2">Backup Files</h4>

          {backupsLoading ? (
            <div className="flex justify-center py-3">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : !files.length ? (
            <p className="text-sm text-muted-foreground">
              No backups yet — use “Create Backup” above.
            </p>
          ) : (() => {
            const selected = files.find((b) => b.filename === effectiveSelected)
            return (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Select
                    value={effectiveSelected}
                    onChange={(e) => setSelectedBackup(e.target.value)}
                    className="flex-1 font-mono text-xs"
                  >
                    {files.map((backup) => (
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
                    <span>{files.length} backup{files.length === 1 ? "" : "s"} total</span>
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
