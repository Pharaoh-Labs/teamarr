import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { SaveButton } from "@/components/ui/save-button"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getSports } from "@/api/teams"
import { getSportDisplayName } from "@/lib/utils"
import {
  useEPGSettings,
  useUpdateEPGSettings,
  useDurationSettings,
  useUpdateDurationSettings,
} from "@/hooks/useSettings"
import type { EPGSettings, DurationSettings } from "@/api/settings"

// Game Thumbs (@sethwv) — optional external service for matchup artwork.
const GAMETHUMBS_REPO_URL = "https://github.com/sethwv/game-thumbs"

/**
 * EPG output settings — output path/window. Lifted out of Settings into the EPG
 * home (v2.7.0 IA). The cron generation scheduler stays in Settings (a system
 * job); only the output-shaping config moves here. The epg fields are part of
 * the shared epg blob (full-PUT), so this loads the COMPLETE epg object and
 * saves it whole. Default durations live in their own component (DefaultDurations).
 */
export function EpgOutputSettings() {
  const { data: epgData } = useEPGSettings()
  const updateEPG = useUpdateEPGSettings()

  const [epg, setEPG] = useState<EPGSettings | null>(null)

  useEffect(() => {
    if (epgData) setEPG(epgData)
  }, [epgData])

  const handleSaveOutput = async () => {
    try {
      if (epg) await updateEPG.mutateAsync(epg)
      toast.success("EPG output settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Output Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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

          <SaveButton onClick={handleSaveOutput} pending={updateEPG.isPending} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Game Thumbs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="art-base-url">Game-Thumbs Base URL</Label>
            <Input
              id="art-base-url"
              placeholder="e.g., https://your-game-thumbs-host"
              value={epg?.art_base_url ?? ""}
              onChange={(e) => epg && setEPG({ ...epg, art_base_url: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Optional. Prefixed onto relative art paths in templates (e.g. a template
              value of <code>/{"{league}"}/{"{home_team}"}/cover.png</code> becomes the full
              URL). Absolute URLs in templates are left unchanged. See the{" "}
              <a
                href={GAMETHUMBS_REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline"
              >
                game-thumbs project
              </a>{" "}
              for setup.
            </p>
          </div>

          <SaveButton onClick={handleSaveOutput} pending={updateEPG.isPending} />
        </CardContent>
      </Card>
    </>
  )
}

/**
 * Default per-sport event durations. Lives at the bottom of the EPG Output page.
 * Uses the standard full-width table styling.
 */
export function DefaultDurations() {
  const { data: durationsData } = useDurationSettings()
  const updateDurations = useUpdateDurationSettings()

  const [durations, setDurations] = useState<DurationSettings | null>(null)

  useEffect(() => {
    if (durationsData) setDurations(durationsData)
  }, [durationsData])

  const { data: sportsData } = useQuery({
    queryKey: ["sports"],
    queryFn: getSports,
    staleTime: 1000 * 60 * 60,
  })
  const sportsMap = sportsData?.sports

  const handleSaveDurations = async () => {
    try {
      if (durations) await updateDurations.mutateAsync(durations)
      toast.success("Default durations saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Default Durations</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Default event durations by sport, in hours.
        </p>
        <div className="border border-border rounded-lg overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Sport</TableHead>
                <TableHead className="text-right">Hours</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {durations &&
                Object.entries(durations)
                  .sort((a, b) =>
                    getSportDisplayName(a[0], sportsMap).localeCompare(
                      getSportDisplayName(b[0], sportsMap)
                    )
                  )
                  .map(([sport, hours]) => (
                    <TableRow key={sport}>
                      <TableCell>{getSportDisplayName(sport, sportsMap)}</TableCell>
                      <TableCell className="text-right">
                        <Input
                          id={`duration-${sport}`}
                          className="w-20 h-8 ml-auto"
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
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>

        <SaveButton onClick={handleSaveDurations} pending={updateDurations.isPending} />
      </CardContent>
    </Card>
  )
}
