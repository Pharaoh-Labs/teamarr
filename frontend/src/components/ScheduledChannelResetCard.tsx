import { useState, useEffect } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { ToggleCard } from "@/components/ui/toggle-card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { CronPreview } from "@/components/CronPreview"
import {
  useSchedulerSettings,
  useUpdateSchedulerSettings,
} from "@/hooks/useSettings"

const RESET_PRESETS: { label: string; cron: string }[] = [
  { label: "Daily 2:30 AM", cron: "30 2 * * *" },
  { label: "Daily 3:30 AM", cron: "30 3 * * *" },
  { label: "Daily 4:30 AM", cron: "30 4 * * *" },
  { label: "Daily 5:30 AM", cron: "30 5 * * *" },
]

/**
 * Scheduled Channel Reset — periodically purges all Teamarr channels in
 * Dispatcharr so the media server's guide refresh picks up fresh logos/data.
 * A media-server-agnostic workaround (originally documented for Jellyfin stale
 * logos); lives in the Media Servers tab as of the v2.7.0 IA overhaul.
 *
 * Self-contained via its own scheduler hooks. Saves only the channel_reset_*
 * fields — the scheduler update is a merge, so this never touches the
 * generation schedule.
 */
export function ScheduledChannelResetCard() {
  const { data: schedulerData } = useSchedulerSettings()
  const updateScheduler = useUpdateSchedulerSettings()

  const [enabled, setEnabled] = useState(false)
  const [cron, setCron] = useState("")

  useEffect(() => {
    if (schedulerData) {
      setEnabled(schedulerData.channel_reset_enabled)
      setCron(schedulerData.channel_reset_cron ?? "")
    }
  }, [schedulerData])

  const handleSave = async () => {
    try {
      await updateScheduler.mutateAsync({
        channel_reset_enabled: enabled,
        channel_reset_cron: cron,
      })
      toast.success("Channel reset settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <ToggleCard
      title="Scheduled Channel Reset"
      description={
        <>
          For users experiencing stale channel logos in their media server. Schedule a periodic
          purge of all Teamarr channels before your media server&apos;s guide refresh.
          Leave disabled if you&apos;re not having issues.
        </>
      }
      enabled={enabled}
      onEnabledChange={setEnabled}
      footer={<SaveButton onClick={handleSave} pending={updateScheduler.isPending} />}
    >
      <div className="space-y-2">
        <Label htmlFor="reset-cron">Reset Schedule (Cron Expression)</Label>
        <Input
          id="reset-cron"
          value={cron}
          onChange={(e) => setCron(e.target.value)}
          className="font-mono"
          placeholder="30 3 * * *"
        />
        <CronPreview expression={cron} />
      </div>

      <div className="flex flex-wrap gap-2">
        {RESET_PRESETS.map((preset) => (
          <Button
            key={preset.cron}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setCron(preset.cron)}
          >
            {preset.label}
          </Button>
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        Set this to run shortly before your media server&apos;s scheduled guide refresh.
        Channels will be recreated on the next EPG generation.
      </p>
    </ToggleCard>
  )
}
