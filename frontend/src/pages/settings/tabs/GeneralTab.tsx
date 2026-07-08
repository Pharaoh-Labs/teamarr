import { useState } from "react"
import { toast } from "sonner"
import { Loader2, Play, ExternalLink, RefreshCw } from "lucide-react"
import { useGenerationProgress } from "@/contexts/GenerationContext"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { ToggleCard } from "@/components/ui/toggle-card"
import { Badge } from "@/components/ui/badge"
import { CronPreview } from "@/components/CronPreview"
import {
  useUpdateSchedulerSettings,
  useSchedulerStatus,
  useUpdateEPGSettings,
  useUpdateDisplaySettings,
  useUpdateCheckSettings,
  useUpdateUpdateCheckSettings,
  useCheckForUpdates,
  useForceCheckForUpdates,
} from "@/hooks/useSettings"
import { useDateFormat } from "@/hooks/useDateFormat"
import type {
  AllSettings,
  UpdateCheckSettings,
  TSDBKeyValidationResult,
} from "@/api/settings"
import { validateTSDBKey } from "@/api/settings"
import { formatRelativeTime } from "../format"

const CRON_PRESETS = [
  { label: "Every Hour", cron: "0 * * * *" },
  { label: "Every 2 Hours", cron: "0 */2 * * *" },
  { label: "Every 4 Hours", cron: "0 */4 * * *" },
  { label: "Every 6 Hours", cron: "0 */6 * * *" },
  { label: "Daily at Midnight", cron: "0 0 * * *" },
  { label: "Daily at 6 AM", cron: "0 6 * * *" },
]

function UpdateNotificationsCard() {
  const { data: updateCheckData } = useUpdateCheckSettings()
  if (!updateCheckData) return null
  return <UpdateNotificationsForm initial={updateCheckData} />
}

function UpdateNotificationsForm({ initial }: { initial: UpdateCheckSettings }) {
  const updateUpdateCheck = useUpdateUpdateCheckSettings()
  const forceCheckUpdates = useForceCheckForUpdates()
  const { formatDateTime } = useDateFormat()
  const [updateCheck, setUpdateCheck] = useState<UpdateCheckSettings>(initial)
  // Gate the version check on the SAVED enabled flag, not the unsaved draft
  const updateInfoQuery = useCheckForUpdates(initial.enabled)

  return (
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
  )
}

export function GeneralTab({ settings }: { settings: AllSettings }) {
  const schedulerStatus = useSchedulerStatus()
  const updateScheduler = useUpdateSchedulerSettings()
  const updateEPG = useUpdateEPGSettings()
  const updateDisplay = useUpdateDisplaySettings()
  const { startGeneration, isGenerating } = useGenerationProgress()

  // Local draft state, initialized from loaded settings. epg and display are
  // shared across cards (timezone + cron live on epg; formats + TSDB key on
  // display), so they stay at tab level.
  const [scheduler, setScheduler] = useState(settings.scheduler)
  const [epg, setEPG] = useState(settings.epg)
  const [display, setDisplay] = useState(settings.display)
  const [tsdbValidation, setTsdbValidation] = useState<TSDBKeyValidationResult | null>(null)
  const [tsdbValidating, setTsdbValidating] = useState(false)

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

  return (
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
                value={settings.ui_timezone ?? "America/New_York"}
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
              {CRON_PRESETS.map((preset) => (
                <Button
                  key={preset.cron}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => epg && setEPG({ ...epg, cron_expression: preset.cron })}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={() => startGeneration()} variant="outline" disabled={isGenerating}>
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

      <UpdateNotificationsCard />
    </>
  )
}
