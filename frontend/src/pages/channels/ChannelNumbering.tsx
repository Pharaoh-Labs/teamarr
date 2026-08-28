import { useState, useEffect, useRef } from "react"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { RadioCards } from "@/components/ui/radio-cards"
import { SortPriorityManager } from "@/components/SortPriorityManager"
import { PinnedBlocks } from "@/components/PinnedBlocks"
import { Button } from "@/components/ui/button"
import { requestChannelRelayout } from "@/api/settings"
import {
  useSettings,
  useUpdateLifecycleSettings,
  useChannelNumberingSettings,
  useUpdateChannelNumberingSettings,
} from "@/hooks/useSettings"
import type { LifecycleSettings, ChannelNumberingSettings } from "@/api/settings"

/**
 * Channels → Numbering. The lineup pipeline: the channel range every unpinned
 * channel numbers from (lifecycle blob), pinned blocks (#333, their own table
 * — saved immediately), number stability (channel-numbering blob), and sort
 * priority. Save full-PUTs the range + stability blobs; this page leaves the
 * consolidation mode and lifecycle timing/buffers untouched, and since only
 * one Channels view mounts at a time the full-PUT is safe.
 */
export function ChannelNumbering() {
  const { data: settings } = useSettings()
  const updateLifecycle = useUpdateLifecycleSettings()
  const { data: channelNumberingData } = useChannelNumberingSettings()
  const updateChannelNumbering = useUpdateChannelNumberingSettings()

  const [lifecycle, setLifecycle] = useState<LifecycleSettings | null>(null)
  const [channelNumbering, setChannelNumbering] = useState<ChannelNumberingSettings>({
    global_channel_mode: "auto",
    league_channel_starts: {},
    global_consolidation_mode: "consolidate",
    channel_stability_mode: "compact",
    channel_gap_size: 3,
    channel_daily_reset_enabled: true,
    channel_daily_reset_time: "04:00",
    force_channel_relayout_pending: false,
  })
  const [channelRangeStart, setChannelRangeStart] = useState("")
  const [channelRangeEnd, setChannelRangeEnd] = useState("")

  const lifecycleInitRef = useRef(false)
  useEffect(() => {
    if (settings && !lifecycleInitRef.current) {
      lifecycleInitRef.current = true
      setLifecycle(settings.lifecycle)
    }
  }, [settings])

  // Re-seed from the server blob on every refetch (render-time "adjust state
  // when props change" pattern — see DispatcharrOutputSettings.tsx).
  const [syncedNumbering, setSyncedNumbering] = useState<typeof channelNumberingData>(undefined)
  if (channelNumberingData && channelNumberingData !== syncedNumbering) {
    setSyncedNumbering(channelNumberingData)
    setChannelNumbering(channelNumberingData)
  }

  const channelRangeInitializedRef = useRef(false)
  useEffect(() => {
    if (lifecycle && !channelRangeInitializedRef.current) {
      channelRangeInitializedRef.current = true
      setChannelRangeStart(lifecycle.channel_range_start?.toString() ?? "101")
      setChannelRangeEnd(lifecycle.channel_range_end?.toString() ?? "")
    }
  }, [lifecycle])

  const handleSave = async () => {
    try {
      const promises: Promise<unknown>[] = [
        // Manual mode is retired (v88); the mode is always auto and the legacy
        // league starts are not sent back.
        updateChannelNumbering.mutateAsync({
          global_consolidation_mode: channelNumbering.global_consolidation_mode,
          channel_stability_mode: channelNumbering.channel_stability_mode,
          channel_gap_size: channelNumbering.channel_gap_size,
          channel_daily_reset_enabled: channelNumbering.channel_daily_reset_enabled,
          channel_daily_reset_time: channelNumbering.channel_daily_reset_time,
        }),
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

  const [regridding, setRegridding] = useState(false)
  const handleRegrid = async () => {
    setRegridding(true)
    try {
      const updated = await requestChannelRelayout()
      setChannelNumbering(updated)
      toast.success("Re-grid queued — channels renumber on the next generation")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to queue re-grid")
    } finally {
      setRegridding(false)
    }
  }

  const rangeStartNum = lifecycle?.channel_range_start ?? 101

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Channel Range</CardTitle>
          <CardDescription>
            Where channels number from. Pinned blocks below carve out their own ranges;
            everything else numbers from here in priority order.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
                First channel number for everything that isn&apos;t pinned
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

          {/* Number Stability — applies inside every block and the range */}
          <div className="space-y-3 pt-2 border-t">
            <div>
              <Label className="text-sm font-medium">Number Stability</Label>
              <p className="text-xs text-muted-foreground mt-1">
                Controls whether a channel can be renumbered while an event is
                live. Dispatcharr relies on stable numbers, so a game shouldn&apos;t
                move when another event starts or ends. Applies inside every pinned
                block as well as the channel range.
              </p>
            </div>
            <RadioCards
              name="channel-stability-mode"
              value={channelNumbering.channel_stability_mode}
              onChange={(v) =>
                setChannelNumbering({
                  ...channelNumbering,
                  channel_stability_mode: v as ChannelNumberingSettings["channel_stability_mode"],
                })
              }
              options={[
                {
                  value: "compact",
                  label: "Compact",
                  description:
                    "Re-sort everything into tidy contiguous order every run. A live channel's number can shift when events start or end.",
                },
                {
                  value: "gap",
                  label: "Gapped (sticky)",
                  description:
                    "Space channels apart on creation. New events fill a gap near where they sort; existing channels keep their number until the daily reset.",
                },
                {
                  value: "strict",
                  label: "Strict (no drift)",
                  description:
                    "Existing channels never move. New channels that would displace others are appended to the end; gaps are reclaimed at the daily reset.",
                },
              ]}
            />

            {channelNumbering.channel_stability_mode === "gap" && (
              <div className="space-y-2 max-w-xs">
                <Label htmlFor="ch-gap-size">Gap Size</Label>
                <Input
                  id="ch-gap-size"
                  type="number"
                  min={1}
                  value={channelNumbering.channel_gap_size}
                  onChange={(e) =>
                    setChannelNumbering({
                      ...channelNumbering,
                      channel_gap_size: Math.max(1, parseInt(e.target.value) || 1),
                    })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Spacing between channels at reset (e.g. 3 → 101, 104, 107).
                  Leaves room for late events to slot in without moving anyone.
                </p>
              </div>
            )}

            {channelNumbering.channel_stability_mode !== "compact" && (
              <div className="space-y-3">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <Switch
                    checked={channelNumbering.channel_daily_reset_enabled}
                    onCheckedChange={(checked) =>
                      setChannelNumbering({
                        ...channelNumbering,
                        channel_daily_reset_enabled: checked,
                      })
                    }
                  />
                  Daily re-layout (reclaim gaps &amp; restore priority order)
                </label>
                {channelNumbering.channel_daily_reset_enabled && (
                  <div className="space-y-2 max-w-xs">
                    <Label htmlFor="ch-reset-time">Reset Time (local)</Label>
                    <Input
                      id="ch-reset-time"
                      type="time"
                      value={channelNumbering.channel_daily_reset_time}
                      onChange={(e) =>
                        setChannelNumbering({
                          ...channelNumbering,
                          channel_daily_reset_time: e.target.value,
                        })
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      The first generation at or after this time re-grids every
                      channel — the only moment existing numbers change. Pick a
                      low-traffic window. Uses the server&apos;s local time (usually
                      UTC in Docker unless the container TZ is set).
                    </p>
                  </div>
                )}

                <div className="space-y-2 pt-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleRegrid}
                    disabled={regridding || channelNumbering.force_channel_relayout_pending}
                  >
                    {channelNumbering.force_channel_relayout_pending
                      ? "Re-grid queued ✓"
                      : regridding
                        ? "Queuing…"
                        : "Re-grid channels now"}
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Renumber every channel back into priority order on the next
                    generation, without waiting for the daily window. Use after
                    changing the gap size, mode, sort priority, or pinned blocks.
                    (These changes also queue a re-grid automatically.)
                  </p>
                </div>
              </div>
            )}
          </div>

          <div className="pt-4 border-t">
            <SaveButton
              onClick={handleSave}
              pending={updateChannelNumbering.isPending || updateLifecycle.isPending}
            />
            <p className="text-xs text-muted-foreground mt-2">
              Channel numbers will be updated on the next EPG generation.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Pinned Blocks — saved immediately, not part of the Save above */}
      <PinnedBlocks rangeStart={rangeStartNum} />

      {/* Channel Ordering — lineup sort priority (within sport → league → time) */}
      <SortPriorityManager
        currentSortBy="sport_league_time"
        showWhenSortBy="sport_league_time"
      />
    </div>
  )
}
