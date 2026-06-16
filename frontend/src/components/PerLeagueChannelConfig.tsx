import { useState, useEffect, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Search, Trash2, ChevronDown, ChevronRight, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { ChannelProfileSelector } from "@/components/ChannelProfileSelector"
import { getLeagues, getSports } from "@/api/teams"
import { cn, getSportDisplayName } from "@/lib/utils"
import {
  useDispatcharrStatus,
  useLeagueConfigs,
  useUpsertLeagueConfig,
  useDeleteLeagueConfig,
} from "@/hooks/useSettings"
import { useSubscription } from "@/hooks/useSubscription"
import type { SubscriptionLeagueConfig } from "@/api/settings"

function LeagueConfigRow({
  leagueName,
  sportName,
  config,
  isExpanded,
  hasOverride,
  channelProfiles,
  channelGroups,
  includeM3uGroups,
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
  channelGroups: { id: number; name: string; from_m3u?: boolean }[]
  includeM3uGroups: boolean
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
      <tr className="hover:bg-muted/30 cursor-pointer" onClick={onToggleExpand}>
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
                  {channelGroups
                    .filter(
                      (g) =>
                        includeM3uGroups || !g.from_m3u || g.id === localGroupId,
                    )
                    .map((g) => (
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

              <div className="flex items-center gap-2">
                <Button size="sm" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save Override"}
                </Button>
                <Button
                  variant="ghost"
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

/**
 * Per-League Channel Config — the per-league counterpart to the global
 * Dispatcharr Output settings. Overrides channel profiles, channel group, and
 * group mode for a specific league; leagues without an override inherit the
 * global defaults. Lives under Channels → Dispatcharr Output (v2.7.0 IA).
 * Self-contained: re-declares the hooks/queries it needs (React Query dedupes
 * by key) and owns its local UI state.
 */
export function PerLeagueChannelConfig() {
  const { data: leagueConfigsData } = useLeagueConfigs()
  const upsertLeagueConfigMutation = useUpsertLeagueConfig()
  const deleteLeagueConfigMutation = useDeleteLeagueConfig()
  const dispatcharrStatus = useDispatcharrStatus()

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

  const [includeM3uGroups] = useState(false)
  const channelGroupsQuery = useQuery({
    queryKey: ["dispatcharr-channel-groups"],
    queryFn: async () => {
      const response = await fetch("/api/v1/dispatcharr/channel-groups?exclude_m3u=false")
      if (!response.ok) return []
      return response.json() as Promise<{ id: number; name: string; from_m3u: boolean }[]>
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })

  const [expandedLeagueConfig, setExpandedLeagueConfig] = useState<string | null>(null)
  const [leagueSearch, setLeagueSearch] = useState("")
  const [showSubscribedOnly, setShowSubscribedOnly] = useState(true)

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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Per-League Channel Config</CardTitle>
        <CardDescription>
          Override channel profiles, channel group, and group mode per league. Leagues without overrides inherit the global defaults above.
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
                      includeM3uGroups={includeM3uGroups}
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
  )
}
