import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { ToggleCard } from "@/components/ui/toggle-card"
import { CheckboxListPicker } from "@/components/ui/checkbox-list-picker"
import {
  useEPGSettings,
  useUpdateEPGSettings,
  useDispatcharrStatus,
} from "@/hooks/useSettings"
import type { EPGSettings } from "@/api/settings"

/**
 * EPG Matching settings — how static-named linear channels are matched to events
 * via Dispatcharr's program guide. Lifted out of Settings into the Matching home
 * (v2.7.0 IA); rendered as a full view under the Matching page SubNav.
 *
 * These fields live in the shared epg blob (full-PUT). This component holds the
 * COMPLETE epg object and saves it whole — only its own fields changed. Safe
 * because only one Matching view is mounted at a time.
 */
export function EpgMatchingSettings() {
  const { data: epgData } = useEPGSettings()
  const updateEPG = useUpdateEPGSettings()
  const dispatcharrStatus = useDispatcharrStatus()

  const [epg, setEPG] = useState<EPGSettings | null>(null)
  useEffect(() => {
    if (epgData) setEPG(epgData)
  }, [epgData])

  const channelGroupsQuery = useQuery({
    queryKey: ["dispatcharr-channel-groups"],
    queryFn: async () => {
      const response = await fetch("/api/v1/dispatcharr/channel-groups?exclude_m3u=true")
      if (!response.ok) return []
      return response.json() as Promise<{ id: number; name: string; from_m3u: boolean }[]>
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Match static-named linear channels (ESPN, NBA1) to events via Dispatcharr's program
        guide, then time-share one stream across event channels. Enabled per Stream Source — tune it here.
      </p>

      {/* Tile 1: Provider EPG Backup */}
      <ToggleCard
        title="Provider EPG Backup"
        enabled={epg?.epg_xtream_fallback_enabled ?? false}
        onEnabledChange={(checked) =>
          epg && setEPG({ ...epg, epg_xtream_fallback_enabled: checked })
        }
        contentClassName="space-y-3"
        always={
          <p className="text-sm text-muted-foreground">
            As a backup, fetch the Xtream (XC) provider's own EPG and match against it —
            covers streams that don't already belong to a Dispatcharr channel.
          </p>
        }
      >
        <div className="max-w-xs">
          <Label htmlFor="epg-xtream-cache">Cache for (hours)</Label>
          <Input
            id="epg-xtream-cache"
            type="number"
            min={1}
            value={epg?.epg_xtream_cache_hours ?? 24}
            onChange={(e) =>
              epg && setEPG({ ...epg, epg_xtream_cache_hours: parseInt(e.target.value) || 1 })
            }
          />
          <p className="text-xs text-muted-foreground pt-1">
            Cached per XC account; re-fetched when older than this. 24h is a good default.
          </p>
        </div>
      </ToggleCard>

      {/* Tile 2: Attach/Detach Timing */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Attach/Detach Timing</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-md">
            <div>
              <Label htmlFor="epg-pre-buffer">Attach before (minutes)</Label>
              <Input
                id="epg-pre-buffer"
                type="number"
                min={0}
                value={epg?.epg_stream_pre_buffer_minutes ?? 60}
                onChange={(e) =>
                  epg && setEPG({ ...epg, epg_stream_pre_buffer_minutes: parseInt(e.target.value) || 0 })
                }
              />
            </div>
            <div>
              <Label htmlFor="epg-post-buffer">Detach after (minutes)</Label>
              <Input
                id="epg-post-buffer"
                type="number"
                min={0}
                value={epg?.epg_stream_post_buffer_minutes ?? 60}
                onChange={(e) =>
                  epg && setEPG({ ...epg, epg_stream_post_buffer_minutes: parseInt(e.target.value) || 0 })
                }
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            How long before an event a matched stream attaches to its channel, and how long
            after it detaches.
          </p>
        </CardContent>
      </Card>

      {/* Tile 3: Dispatcharr as a Stream Source */}
      <ToggleCard
        title="Dispatcharr as a Stream Source"
        enabled={epg?.epg_channel_source_enabled ?? false}
        onEnabledChange={(checked) =>
          epg && setEPG({ ...epg, epg_channel_source_enabled: checked })
        }
        contentClassName="space-y-3"
        always={
          <p className="text-sm text-muted-foreground">
            Pull candidate streams from the channels you've curated in Dispatcharr, using each
            channel's own EPG — so you match only your mapped channel versions, not every stream
            in a provider group. Teamarr's own channels are excluded.
          </p>
        }
      >
        <div className="max-w-md">
          <CheckboxListPicker
            label="Dispatcharr groups to include"
            selected={(epg?.epg_channel_source_groups ?? []).map(String)}
            onChange={(vals) =>
              epg && setEPG({ ...epg, epg_channel_source_groups: vals.map(Number) })
            }
            items={(channelGroupsQuery.data ?? []).map((g) => ({
              value: String(g.id),
              label: g.name,
            }))}
            searchPlaceholder="Search Dispatcharr groups..."
          />
          <p className="text-xs text-muted-foreground pt-1">
            Only these groups are scanned — fewer = faster. Empty = all. They also become
            sort options under Channels → Stream Priority.
          </p>
        </div>
      </ToggleCard>

      <SaveButton
        onClick={async () => {
          try {
            if (epg) await updateEPG.mutateAsync(epg)
            toast.success("EPG matching settings saved")
          } catch (err) {
            toast.error(err instanceof Error ? err.message : "Failed to save")
          }
        }}
        pending={updateEPG.isPending}
      />
    </div>
  )
}

/**
 * Event Lookahead setting — how many days of upcoming events to match streams
 * against. Part of the shared epg blob (full-PUT); this component holds the
 * COMPLETE epg object and saves it whole. Safe because only one Matching view is
 * mounted at a time.
 */
export function EventLookaheadSetting() {
  const { data: epgData } = useEPGSettings()
  const updateEPG = useUpdateEPGSettings()

  const [epg, setEPG] = useState<EPGSettings | null>(null)
  useEffect(() => {
    if (epgData) setEPG(epgData)
  }, [epgData])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Event Lookahead</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2 max-w-xs">
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
            How many days of upcoming events to match streams against.
          </p>
        </div>

        <SaveButton
          onClick={async () => {
            try {
              if (epg) await updateEPG.mutateAsync(epg)
              toast.success("Event matching settings saved")
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Failed to save")
            }
          }}
          pending={updateEPG.isPending}
        />
      </CardContent>
    </Card>
  )
}
