import { useState, useEffect, useRef, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Search } from "lucide-react"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { RadioCards } from "@/components/ui/radio-cards"
import { SortPriorityManager } from "@/components/SortPriorityManager"
import { Button } from "@/components/ui/button"
import { getLeagues, getSports } from "@/api/teams"
import { requestChannelRelayout } from "@/api/settings"
import { getSportDisplayName } from "@/lib/utils"
import {
  useSettings,
  useUpdateLifecycleSettings,
  useChannelNumberingSettings,
  useUpdateChannelNumberingSettings,
} from "@/hooks/useSettings"
import { useSubscription } from "@/hooks/useSubscription"
import type { LifecycleSettings, ChannelNumberingSettings } from "@/api/settings"

/**
 * Channels → Numbering. The lineup pipeline: how channels are ordered (sort
 * priority) and what numbers they're assigned. Numbering mode and per-league
 * starts live in the channel-numbering blob; the channel range lives in the
 * lifecycle blob — Save full-PUTs both. This page leaves the consolidation mode
 * (channel-numbering) and timing/buffers (lifecycle) untouched, and since only
 * one Channels view mounts at a time the full-PUT is safe.
 */
export function ChannelNumbering() {
  const { data: settings } = useSettings()
  const updateLifecycle = useUpdateLifecycleSettings()
  const { data: channelNumberingData } = useChannelNumberingSettings()
  const updateChannelNumbering = useUpdateChannelNumberingSettings()

  const { data: subscription } = useSubscription()
  const subscribedLeagueSlugs = useMemo(
    () => new Set(subscription?.leagues ?? []),
    [subscription]
  )

  const { data: leaguesData } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(),
  })
  const { data: sportsData } = useQuery({
    queryKey: ["sports"],
    queryFn: getSports,
    staleTime: 1000 * 60 * 60,
  })
  const sportsMap = sportsData?.sports

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
  const [leagueSearch, setLeagueSearch] = useState("")
  const [showSubscribedOnly, setShowSubscribedOnly] = useState(true)

  const lifecycleInitRef = useRef(false)
  useEffect(() => {
    if (settings && !lifecycleInitRef.current) {
      lifecycleInitRef.current = true
      setLifecycle(settings.lifecycle)
    }
  }, [settings])

  useEffect(() => {
    if (channelNumberingData) setChannelNumbering(channelNumberingData)
  }, [channelNumberingData])

  const channelRangeInitializedRef = useRef(false)
  useEffect(() => {
    if (lifecycle && !channelRangeInitializedRef.current) {
      channelRangeInitializedRef.current = true
      setChannelRangeStart(lifecycle.channel_range_start?.toString() ?? "101")
      setChannelRangeEnd(lifecycle.channel_range_end?.toString() ?? "")
    }
  }, [lifecycle])

  const filteredLeagues = useMemo(() => {
    const all = leaguesData?.leagues ?? []
    const searchLower = leagueSearch.toLowerCase()
    return all
      .filter((l) => {
        if (showSubscribedOnly && !subscribedLeagueSlugs.has(l.slug)) return false
        if (searchLower && !(l.name ?? "").toLowerCase().includes(searchLower)
            && !(l.sport ?? "").toLowerCase().includes(searchLower)) return false
        return true
      })
      .sort((a, b) => {
        const sportCmp = (a.sport ?? "").localeCompare(b.sport ?? "")
        if (sportCmp !== 0) return sportCmp
        return (a.name ?? "").localeCompare(b.name ?? "")
      })
  }, [leaguesData, leagueSearch, showSubscribedOnly, subscribedLeagueSlugs])

  const handleSave = async () => {
    try {
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

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Channel Numbering</CardTitle>
          <CardDescription>
            How channel numbers are assigned and ordered in the lineup
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Numbering Mode Toggle */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Numbering Mode</Label>
            <RadioCards
              name="channel-mode"
              value={channelNumbering.global_channel_mode}
              onChange={(v) =>
                setChannelNumbering({ ...channelNumbering, global_channel_mode: v })
              }
              options={[
                {
                  value: "auto",
                  label: "Auto",
                  description:
                    "Sequential numbering from channel range start. Ordered by sport/league priority.",
                },
                {
                  value: "manual",
                  label: "Manual",
                  description:
                    "Per-league starting channel numbers. Each league gets its own number range.",
                },
              ]}
            />
          </div>

          {/* Channel Range (both modes) */}
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

          {/* Number Stability (Auto mode only) */}
          {channelNumbering.global_channel_mode === "auto" && (
            <div className="space-y-3 pt-2 border-t">
              <div>
                <Label className="text-sm font-medium">Number Stability</Label>
                <p className="text-xs text-muted-foreground mt-1">
                  Controls whether a channel can be renumbered while an event is
                  live. Dispatcharr relies on stable numbers, so a game shouldn't
                  move when another event starts or ends.
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
                        low-traffic window. Uses the server's local time (usually
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
                      changing the gap size, mode, or sort priority. (These changes
                      also queue a re-grid automatically.)
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

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

      {/* Channel Ordering — lineup sort priority (within sport → league → time) */}
      <SortPriorityManager
        currentSortBy="sport_league_time"
        showWhenSortBy="sport_league_time"
      />
    </div>
  )
}
