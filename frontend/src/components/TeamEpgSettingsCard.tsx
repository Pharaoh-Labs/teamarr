import { useState } from "react"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import {
  useEPGSettings,
  useDisplaySettings,
  useUpdateEPGSettings,
  useUpdateDisplaySettings,
} from "@/hooks/useSettings"
import type { EPGSettings, DisplaySettings } from "@/api/settings"

/**
 * Team-based EPG settings (schedule days, midnight crossover, channel-id format).
 * Lifted out of Settings into the Team EPG home (v2.7.0 IA).
 *
 * NOTE: these fields live in the shared epg/display settings blobs, which the
 * backend saves as a full PUT. So this card loads the COMPLETE epg + display
 * objects and saves them whole (only its own fields changed) — never a partial
 * — to avoid clobbering fields owned by other homes (Matching, EPG, Settings).
 */
export function TeamEpgSettingsCard() {
  const { data: epgData } = useEPGSettings()
  const { data: displayData } = useDisplaySettings()
  const updateEPG = useUpdateEPGSettings()
  const updateDisplay = useUpdateDisplaySettings()

  const [epg, setEPG] = useState<EPGSettings | null>(null)
  const [display, setDisplay] = useState<DisplaySettings | null>(null)

  // Sync the forms from the server data during render (React's "adjusting
  // state when a prop changes" pattern) — re-seeds on every refetch, exactly
  // like the previous effects, without the extra effect render pass.
  const [syncedEpgData, setSyncedEpgData] = useState<typeof epgData>(undefined)
  if (epgData && epgData !== syncedEpgData) {
    setSyncedEpgData(epgData)
    setEPG(epgData)
  }
  const [syncedDisplayData, setSyncedDisplayData] =
    useState<typeof displayData>(undefined)
  if (displayData && displayData !== syncedDisplayData) {
    setSyncedDisplayData(displayData)
    setDisplay(displayData)
  }

  const handleSave = async () => {
    try {
      const promises: Promise<unknown>[] = []
      if (display) promises.push(updateDisplay.mutateAsync(display))
      if (epg) promises.push(updateEPG.mutateAsync(epg))
      await Promise.all(promises)
      toast.success("Team EPG settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Team EPG Settings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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

        <SaveButton
          onClick={handleSave}
          pending={updateEPG.isPending || updateDisplay.isPending}
        />
      </CardContent>
    </Card>
  )
}
