import { useState, useEffect, useMemo, useCallback } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { ArrowLeft, Loader2, FlaskConical } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { jsToPython, pythonToJs } from "@/lib/regex-utils"
import {
  useGroup,
  useCreateGroup,
  useUpdateGroup,
} from "@/hooks/useGroups"
import type { EventGroupCreate, EventGroupUpdate } from "@/api/types"
import { TeamPicker } from "@/components/TeamPicker"
import { StreamTimezoneSelector } from "@/components/StreamTimezoneSelector"
import { TestPatternsModal, type PatternState } from "@/components/TestPatternsModal"
import { LeaguePicker } from "@/components/LeaguePicker"
import { SoccerModeSelector, type SoccerMode } from "@/components/SoccerModeSelector"
import { getLeagues } from "@/api/teams"
import { getSubscription } from "@/api/subscription"
import type { SoccerFollowedTeam } from "@/api/types"

export function EventGroupForm() {
  const { groupId } = useParams<{ groupId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const isEdit = groupId && groupId !== "new"

  // M3U group info from URL params (when coming from Import)
  const m3uGroupId = searchParams.get("m3u_group_id")
  const m3uGroupName = searchParams.get("m3u_group_name")
  const m3uAccountId = searchParams.get("m3u_account_id")
  const m3uAccountName = searchParams.get("m3u_account_name")

  // Form state
  const [formData, setFormData] = useState<EventGroupCreate>({
    name: m3uGroupName || "",
    display_name: null,  // Optional display name override
    leagues: [],
    sort_order: 0,
    total_stream_count: 0,
    m3u_group_id: m3uGroupId ? Number(m3uGroupId) : null,
    m3u_group_name: m3uGroupName || null,
    m3u_account_id: m3uAccountId ? Number(m3uAccountId) : null,
    m3u_account_name: m3uAccountName || null,
    enabled: true,
    // Team filtering
    include_teams: null,
    exclude_teams: null,
    team_filter_mode: "include",
    bypass_filter_for_playoffs: null,  // null = use default
  })

  // Fetch existing group if editing
  const { data: group, isLoading: isLoadingGroup } = useGroup(
    isEdit ? Number(groupId) : 0
  )

  // Custom Regex event type tab
  type EventTypeTab = "team_vs_team" | "event_card"
  const [regexEventType, setRegexEventType] = useState<EventTypeTab>("team_vs_team")

  // Test Patterns modal
  const [testPatternsOpen, setTestPatternsOpen] = useState(false)

  // Team filter default state - true = use global default, false = custom per-group filter
  const [useDefaultTeamFilter, setUseDefaultTeamFilter] = useState(true)

  // Subscription override state - true = use global subscription, false = custom per-group
  const [useGlobalSubscription, setUseGlobalSubscription] = useState(true)
  const [overrideNonSoccerLeagues, setOverrideNonSoccerLeagues] = useState<string[]>([])
  const [overrideSoccerMode, setOverrideSoccerMode] = useState<SoccerMode>(null)
  const [overrideSoccerLeagues, setOverrideSoccerLeagues] = useState<string[]>([])
  const [overrideFollowedTeams, setOverrideFollowedTeams] = useState<SoccerFollowedTeam[]>([])
  const [matchingGlobal, setMatchingGlobal] = useState(false)

  // Fetch leagues for splitting soccer vs non-soccer
  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
  })
  const allLeagues = leaguesData?.leagues || []

  const matchGlobal = useCallback(async () => {
    setMatchingGlobal(true)
    try {
      const sub = await getSubscription()
      const soccer: string[] = []
      const nonSoccer: string[] = []
      for (const slug of sub.leagues) {
        const league = allLeagues.find((l) => l.slug === slug)
        if (league?.sport?.toLowerCase() === "soccer") {
          soccer.push(slug)
        } else {
          nonSoccer.push(slug)
        }
      }
      setOverrideNonSoccerLeagues(nonSoccer)
      setOverrideSoccerLeagues(soccer)
      setOverrideSoccerMode((sub.soccer_mode as SoccerMode) || null)
      setOverrideFollowedTeams(sub.soccer_followed_teams || [])
    } catch {
      toast.error("Failed to load global subscription")
    } finally {
      setMatchingGlobal(false)
    }
  }, [allLeagues])

  // Mutations
  const createMutation = useCreateGroup()
  const updateMutation = useUpdateGroup()

  // Test Patterns modal — bidirectional sync with form
  const currentPatterns = useMemo<Partial<PatternState>>(() => ({
    skip_builtin_filter: formData.skip_builtin_filter ?? false,
    stream_include_regex: formData.stream_include_regex ?? null,
    stream_include_regex_enabled: formData.stream_include_regex_enabled ?? false,
    stream_exclude_regex: formData.stream_exclude_regex ?? null,
    stream_exclude_regex_enabled: formData.stream_exclude_regex_enabled ?? false,
    custom_regex_teams: formData.custom_regex_teams ?? null,
    custom_regex_teams_enabled: formData.custom_regex_teams_enabled ?? false,
    custom_regex_date: formData.custom_regex_date ?? null,
    custom_regex_date_enabled: formData.custom_regex_date_enabled ?? false,
    custom_regex_month: formData.custom_regex_month ?? null,
    custom_regex_month_enabled: formData.custom_regex_month_enabled ?? false,
    custom_regex_day: formData.custom_regex_day ?? null,
    custom_regex_day_enabled: formData.custom_regex_day_enabled ?? false,
    custom_regex_time: formData.custom_regex_time ?? null,
    custom_regex_time_enabled: formData.custom_regex_time_enabled ?? false,
    custom_regex_league: formData.custom_regex_league ?? null,
    custom_regex_league_enabled: formData.custom_regex_league_enabled ?? false,
    custom_regex_fighters: formData.custom_regex_fighters ?? null,
    custom_regex_fighters_enabled: formData.custom_regex_fighters_enabled ?? false,
    custom_regex_event_name: formData.custom_regex_event_name ?? null,
    custom_regex_event_name_enabled: formData.custom_regex_event_name_enabled ?? false,
  }), [formData])

  // Populate form when editing
  useEffect(() => {
    if (group) {
      setFormData({
        name: group.name,
        display_name: group.display_name,
        leagues: group.leagues,
        stream_timezone: group.stream_timezone,  // Keep null = "auto-detect from stream"
        sort_order: group.sort_order,
        total_stream_count: group.total_stream_count,
        m3u_group_id: group.m3u_group_id,
        m3u_group_name: group.m3u_group_name,
        m3u_account_id: group.m3u_account_id,
        m3u_account_name: group.m3u_account_name,
        // Stream filtering
        stream_include_regex: group.stream_include_regex ? pythonToJs(group.stream_include_regex) : null,
        stream_include_regex_enabled: group.stream_include_regex_enabled,
        stream_exclude_regex: group.stream_exclude_regex ? pythonToJs(group.stream_exclude_regex) : null,
        stream_exclude_regex_enabled: group.stream_exclude_regex_enabled,
        custom_regex_teams: group.custom_regex_teams ? pythonToJs(group.custom_regex_teams) : null,
        custom_regex_teams_enabled: group.custom_regex_teams_enabled,
        custom_regex_date: group.custom_regex_date ? pythonToJs(group.custom_regex_date) : null,
        custom_regex_date_enabled: group.custom_regex_date_enabled,
        custom_regex_month: group.custom_regex_month ? pythonToJs(group.custom_regex_month) : null,
        custom_regex_month_enabled: group.custom_regex_month_enabled,
        custom_regex_day: group.custom_regex_day ? pythonToJs(group.custom_regex_day) : null,
        custom_regex_day_enabled: group.custom_regex_day_enabled,
        custom_regex_time: group.custom_regex_time ? pythonToJs(group.custom_regex_time) : null,
        custom_regex_time_enabled: group.custom_regex_time_enabled,
        custom_regex_league: group.custom_regex_league ? pythonToJs(group.custom_regex_league) : null,
        custom_regex_league_enabled: group.custom_regex_league_enabled,
        // EVENT_CARD specific
        custom_regex_fighters: group.custom_regex_fighters ? pythonToJs(group.custom_regex_fighters) : null,
        custom_regex_fighters_enabled: group.custom_regex_fighters_enabled,
        custom_regex_event_name: group.custom_regex_event_name ? pythonToJs(group.custom_regex_event_name) : null,
        custom_regex_event_name_enabled: group.custom_regex_event_name_enabled,
        skip_builtin_filter: group.skip_builtin_filter,
        team_streams_enabled: group.team_streams_enabled,
        epg_match_enabled: group.epg_match_enabled,
        // Team filtering
        include_teams: group.include_teams,
        exclude_teams: group.exclude_teams,
        team_filter_mode: group.team_filter_mode || "include",
        bypass_filter_for_playoffs: group.bypass_filter_for_playoffs,
        enabled: group.enabled,
      })

      // Set useDefaultTeamFilter based on whether include_teams/exclude_teams are null (use default)
      // null means use global default, any array (even empty) means custom per-group filter
      const hasCustomTeamFilter = group.include_teams !== null || group.exclude_teams !== null
      setUseDefaultTeamFilter(!hasCustomTeamFilter)

      // Set subscription override state
      const hasSubscriptionOverride = group.subscription_leagues !== null
      setUseGlobalSubscription(!hasSubscriptionOverride)
      if (hasSubscriptionOverride && group.subscription_leagues) {
        // Split subscription_leagues into soccer vs non-soccer
        const soccer: string[] = []
        const nonSoccer: string[] = []
        for (const slug of group.subscription_leagues) {
          const league = allLeagues.find((l) => l.slug === slug)
          if (league?.sport?.toLowerCase() === "soccer") {
            soccer.push(slug)
          } else {
            nonSoccer.push(slug)
          }
        }
        setOverrideNonSoccerLeagues(nonSoccer)
        setOverrideSoccerLeagues(soccer)
        setOverrideSoccerMode((group.subscription_soccer_mode as SoccerMode) || null)
        setOverrideFollowedTeams(group.subscription_soccer_followed_teams || [])
      }
    }
  }, [group, allLeagues])

  // `overrides` lets callers (e.g. Apply-to-Form) save with freshly-merged
  // patterns without waiting for the async setFormData to flush.
  const handleSubmit = async (overrides?: Partial<typeof formData>) => {
    const data = overrides ? { ...formData, ...overrides } : formData
    if (!data.name.trim()) {
      toast.error("Group name is required")
      return
    }

    try {
      const submitData = {
        ...data,
        stream_include_regex: data.stream_include_regex ? jsToPython(data.stream_include_regex) : null,
        stream_exclude_regex: data.stream_exclude_regex ? jsToPython(data.stream_exclude_regex) : null,
        custom_regex_teams: data.custom_regex_teams ? jsToPython(data.custom_regex_teams) : null,
        custom_regex_date: data.custom_regex_date ? jsToPython(data.custom_regex_date) : null,
        custom_regex_month: data.custom_regex_month ? jsToPython(data.custom_regex_month) : null,
        custom_regex_day: data.custom_regex_day ? jsToPython(data.custom_regex_day) : null,
        custom_regex_time: data.custom_regex_time ? jsToPython(data.custom_regex_time) : null,
        custom_regex_league: data.custom_regex_league ? jsToPython(data.custom_regex_league) : null,
        custom_regex_fighters: data.custom_regex_fighters ? jsToPython(data.custom_regex_fighters) : null,
        custom_regex_event_name: data.custom_regex_event_name ? jsToPython(data.custom_regex_event_name) : null,
        // Subscription override fields
        subscription_leagues: useGlobalSubscription
          ? null
          : [...overrideNonSoccerLeagues, ...overrideSoccerLeagues],
        subscription_soccer_mode: useGlobalSubscription ? null : overrideSoccerMode,
        subscription_soccer_followed_teams: useGlobalSubscription
          ? null
          : (overrideFollowedTeams.length > 0 ? overrideFollowedTeams : null),
      }

      if (isEdit) {
        const updateData: EventGroupUpdate = { ...submitData }

        // Compute clear flags for nullable fields that were changed from a value to null/undefined
        // This is required because the backend only clears fields when explicit clear_* flags are set
        if (group) {
          const shouldClear = (original: unknown, current: unknown) =>
            original != null && (current == null || current === undefined)

          if (shouldClear(group.display_name, data.display_name)) {
            updateData.clear_display_name = true
          }
          if (shouldClear(group.stream_timezone, data.stream_timezone)) {
            updateData.clear_stream_timezone = true
          }
          // Clear subscription override when switching back to global
          if (useGlobalSubscription && group.subscription_leagues !== null) {
            updateData.clear_subscription_leagues = true
            updateData.clear_subscription_soccer_mode = true
            updateData.clear_subscription_soccer_followed_teams = true
          }
        }

        await updateMutation.mutateAsync({ groupId: Number(groupId), data: updateData })
        toast.success(`Updated group "${data.name}"`)
      } else {
        await createMutation.mutateAsync(submitData)
        toast.success(`Created group "${data.name}"`)
      }
      navigate("/sources")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save group")
    }
  }

  // Apply-to-Form from the Pattern Tester writes the patterns into the form AND
  // saves — a frequent ask, since people forgot the separate Save after applying.
  // Pass the patterns to handleSubmit directly so the save uses them immediately
  // (setFormData hasn't flushed yet).
  const handlePatternsApply = (patterns: PatternState) => {
    setFormData((prev) => ({ ...prev, ...patterns }))
    void handleSubmit(patterns)
  }

  if (isEdit && isLoadingGroup) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate("/sources")}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">
            {isEdit ? "Edit Stream Source" : "Configure Stream Source"}
          </h1>
          {m3uGroupName && !isEdit && (
            <p className="text-muted-foreground">
              Importing: <span className="font-medium">{m3uGroupName}</span>
            </p>
          )}
        </div>
      </div>

      {/* Settings Section */}
      <div className="space-y-6">
          {/* Basic Settings (name and enabled only, for new groups without full edit context) */}
          {!isEdit && (
            <CollapsibleSection title="Basic Settings" defaultCollapsed={false} persistKey="sources-form.basic">
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Group Name</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    readOnly
                    className="bg-muted"
                  />
                  <p className="text-xs text-muted-foreground">Name from M3U group</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="display_name_new">Display Name (Optional)</Label>
                  <Input
                    id="display_name_new"
                    value={formData.display_name || ""}
                    onChange={(e) => setFormData({ ...formData, display_name: e.target.value || null })}
                    placeholder="Override name for display in UI"
                  />
                  <p className="text-xs text-muted-foreground">
                    If set, this name will be shown instead of the M3U group name
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={formData.enabled}
                    onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
                  />
                  <Label className="font-normal">Enabled</Label>
                </div>

                <div className="flex items-center gap-2">
                  <Switch
                    checked={formData.team_streams_enabled || false}
                    onCheckedChange={(checked) => setFormData({ ...formData, team_streams_enabled: checked })}
                  />
                  <div>
                    <Label className="font-normal">Team stream source</Label>
                    <p className="text-xs text-muted-foreground">
                      Allow team-branded streams (e.g. "NHL | Toronto Maple Leafs") to match events where that team plays. Built-in stream filtering is automatically bypassed for this group.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Switch
                    checked={formData.epg_match_enabled || false}
                    onCheckedChange={(checked) => setFormData({ ...formData, epg_match_enabled: checked })}
                  />
                  <div>
                    <Label className="font-normal">EPG program matching</Label>
                    <p className="text-xs text-muted-foreground">
                      Match static-named linear channels (e.g. "ESPN", "NBA1") to events using Dispatcharr's program guide, and time-share one stream across multiple event channels near game time. Requires the global EPG matching switch (Settings &rarr; EPG). Built-in filtering is bypassed for this group.
                    </p>
                  </div>
                </div>
              </div>
            </CollapsibleSection>
          )}

          {/* Basic Info (edit mode) */}
          {isEdit && <CollapsibleSection title="Basic Settings" defaultCollapsed={false} persistKey="sources-form.basic">
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Group Name</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    readOnly
                    className="bg-muted"
                  />
                  <p className="text-xs text-muted-foreground">Name from M3U group</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="display_name">Display Name (Optional)</Label>
                  <Input
                    id="display_name"
                    value={formData.display_name || ""}
                    onChange={(e) => setFormData({ ...formData, display_name: e.target.value || null })}
                    placeholder="Override name for display in UI"
                  />
                  <p className="text-xs text-muted-foreground">
                    If set, shown instead of M3U group name
                  </p>
                </div>
              </div>

              {/* M3U Source Info - watermark style */}
              {formData.m3u_group_name && (
                <div className="text-xs text-muted-foreground/70 pt-3">
                  {formData.m3u_account_name && (
                    <div>M3U: {formData.m3u_account_name} (#{formData.m3u_account_id})</div>
                  )}
                  <div>Group: {formData.m3u_group_name} (#{formData.m3u_group_id})</div>
                </div>
              )}

              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.enabled}
                  onCheckedChange={(checked) => setFormData({ ...formData, enabled: checked })}
                />
                <Label className="font-normal">Enabled</Label>
              </div>

              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.team_streams_enabled || false}
                  onCheckedChange={(checked) => setFormData({ ...formData, team_streams_enabled: checked })}
                />
                <div>
                  <Label className="font-normal">Team stream source</Label>
                  <p className="text-xs text-muted-foreground">
                    Allow team-branded streams (e.g. "NHL | Toronto Maple Leafs") to match events where that team plays. Built-in stream filtering is automatically bypassed for this group.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.epg_match_enabled || false}
                  onCheckedChange={(checked) => setFormData({ ...formData, epg_match_enabled: checked })}
                />
                <div>
                  <Label className="font-normal">EPG program matching</Label>
                  <p className="text-xs text-muted-foreground">
                    Match static-named linear channels (e.g. "ESPN", "NBA1") to events using Dispatcharr's program guide, and time-share one stream across multiple event channels near game time. Requires the global EPG matching switch (Settings &rarr; EPG). Built-in filtering is bypassed for this group.
                  </p>
                </div>
              </div>
            </div>
          </CollapsibleSection>}

          {/* Subscription Override */}
          <CollapsibleSection
            title="Subscription Override"
            defaultCollapsed
            persistKey="sources-form.subscription"
            count={!useGlobalSubscription ? (
              <span className="text-xs text-amber-500 font-medium">Custom</span>
            ) : undefined}
          >
              <div className="space-y-4">
                <label className="flex items-center gap-2 mb-2 cursor-pointer">
                  <Checkbox
                    checked={useGlobalSubscription}
                    onCheckedChange={() => {
                      const newValue = !useGlobalSubscription
                      setUseGlobalSubscription(newValue)
                      if (newValue) {
                        // Revert to global — clear local override state
                        setOverrideNonSoccerLeagues([])
                        setOverrideSoccerLeagues([])
                        setOverrideSoccerMode(null)
                        setOverrideFollowedTeams([])
                      } else {
                        // Entering override mode — seed from global subscription
                        matchGlobal()
                      }
                    }}
                  />
                  <span className="text-sm font-normal">
                    Use global subscription (set on the Subscriptions page)
                  </span>
                </label>

                {!useGlobalSubscription && (
                  <>
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-muted-foreground">
                        Override which leagues this group matches against instead of using the global subscription.
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={matchGlobal}
                        disabled={matchingGlobal}
                      >
                        {matchingGlobal ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : null}
                        Match Global
                      </Button>
                    </div>

                    {/* Non-Soccer Sports */}
                    <div className="space-y-2">
                      <Label className="text-sm font-medium">Non-Soccer Sports</Label>
                      <LeaguePicker
                        selectedLeagues={overrideNonSoccerLeagues}
                        onSelectionChange={setOverrideNonSoccerLeagues}
                        excludeSport="soccer"
                        maxHeight="max-h-48"
                        showSearch={true}
                        showSelectedBadges={true}
                        maxBadges={8}
                      />
                    </div>

                    <div className="border-t" />

                    {/* Soccer */}
                    <div className="space-y-2">
                      <Label className="text-sm font-medium">Soccer Leagues</Label>
                      <SoccerModeSelector
                        mode={overrideSoccerMode}
                        onModeChange={setOverrideSoccerMode}
                        selectedLeagues={overrideSoccerLeagues}
                        onLeaguesChange={setOverrideSoccerLeagues}
                        followedTeams={overrideFollowedTeams}
                        onFollowedTeamsChange={setOverrideFollowedTeams}
                      />
                    </div>
                  </>
                )}
              </div>
          </CollapsibleSection>

          {/* Team Filtering */}
          <CollapsibleSection title="Team Filtering" defaultCollapsed persistKey="sources-form.teamfilter">
                <div className="space-y-4">
                  {/* Use default toggle */}
                  <label className="flex items-center gap-2 mb-2 cursor-pointer">
                    <Checkbox
                      checked={useDefaultTeamFilter}
                      onCheckedChange={() => {
                        const newValue = !useDefaultTeamFilter
                        setUseDefaultTeamFilter(newValue)
                        if (newValue) {
                          setFormData({
                            ...formData,
                            include_teams: null,
                            exclude_teams: null,
                          })
                        } else {
                          setFormData({
                            ...formData,
                            include_teams: [],
                            exclude_teams: [],
                          })
                        }
                      }}
                    />
                    <span className="text-sm font-normal">
                      Use default team filter (set in Global Defaults above)
                    </span>
                  </label>

                  {!useDefaultTeamFilter && (
                    <>
                      <p className="text-sm text-muted-foreground">
                        Configure a custom team filter for this group.
                      </p>

                      {/* Mode selector */}
                      <div className="flex gap-4">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio"
                            name="team_filter_mode"
                            value="include"
                            checked={formData.team_filter_mode === "include"}
                            onChange={() => {
                              // Move teams to include list when switching modes
                              const teams = formData.exclude_teams || []
                              setFormData({
                                ...formData,
                                team_filter_mode: "include",
                                include_teams: teams.length > 0 ? teams : formData.include_teams,
                                exclude_teams: [],
                              })
                            }}
                            className="accent-primary"
                          />
                          <span className="text-sm">Include only selected teams</span>
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio"
                            name="team_filter_mode"
                            value="exclude"
                            checked={formData.team_filter_mode === "exclude"}
                            onChange={() => {
                              // Move teams to exclude list when switching modes
                              const teams = formData.include_teams || []
                              setFormData({
                                ...formData,
                                team_filter_mode: "exclude",
                                exclude_teams: teams.length > 0 ? teams : formData.exclude_teams,
                                include_teams: [],
                              })
                            }}
                            className="accent-primary"
                          />
                          <span className="text-sm">Exclude selected teams</span>
                        </label>
                      </div>

                      {/* Team picker */}
                      <TeamPicker
                        leagues={formData.leagues}
                        selectedTeams={
                          formData.team_filter_mode === "include"
                            ? (formData.include_teams || [])
                            : (formData.exclude_teams || [])
                        }
                        onSelectionChange={(teams) => {
                          if (formData.team_filter_mode === "include") {
                            setFormData({
                              ...formData,
                              include_teams: teams,
                              exclude_teams: [],
                            })
                          } else {
                            setFormData({
                              ...formData,
                              exclude_teams: teams,
                              include_teams: [],
                            })
                          }
                        }}
                      />

                      {/* Playoff bypass option */}
                      <label className="flex items-center gap-2 cursor-pointer py-2">
                        <Checkbox
                          checked={formData.bypass_filter_for_playoffs ?? false}
                          onCheckedChange={(checked) =>
                            setFormData({
                              ...formData,
                              bypass_filter_for_playoffs: checked ? true : null,
                            })
                          }
                        />
                        <span className="text-sm">
                          Include all playoff games (bypass team filter for postseason)
                        </span>
                      </label>
                      <p className="text-xs text-muted-foreground -mt-1 ml-6">
                        Unchecked uses the global default from Settings
                      </p>

                      <div className="space-y-1 mt-2">
                        <p className="text-xs text-muted-foreground">
                          {!(formData.include_teams?.length || formData.exclude_teams?.length)
                            ? "No teams selected. All events will be matched."
                            : formData.team_filter_mode === "include"
                              ? `Only events involving ${formData.include_teams?.length} selected team(s) will be matched.`
                              : `Events involving ${formData.exclude_teams?.length} selected team(s) will be excluded.`}
                        </p>
                        {(formData.include_teams?.length || formData.exclude_teams?.length) ? (
                          <p className="text-xs text-muted-foreground italic">
                            Filter only applies to leagues where you've made selections.
                          </p>
                        ) : null}
                      </div>
                    </>
                  )}
                </div>
          </CollapsibleSection>

          {/* Custom Regex */}
          <CollapsibleSection title="Custom Regex" defaultCollapsed persistKey="sources-form.regex">
              <div className="space-y-6">
                {/* Pattern Tester - only in edit mode */}
                {isEdit && (
                  <div className="pb-4 border-b">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setTestPatternsOpen(true)}
                      className="gap-2"
                    >
                      <FlaskConical className="h-4 w-4" />
                      Open Pattern Tester
                    </Button>
                    <p className="text-xs text-muted-foreground mt-2">
                      Test your regex patterns against actual stream names from this group
                    </p>
                  </div>
                )}

                {/* Stream Filtering Subsection */}
                <div className="space-y-4">
                  {/* Skip Builtin Filter */}
                  <label className="flex items-center gap-3 cursor-pointer">
                    <Checkbox
                      checked={formData.skip_builtin_filter || false}
                      onCheckedChange={() =>
                        setFormData({ ...formData, skip_builtin_filter: !formData.skip_builtin_filter })
                      }
                    />
                    <div>
                      <span className="text-sm font-normal">
                        Skip built-in stream filtering
                      </span>
                      <p className="text-xs text-muted-foreground">
                        Bypass placeholder detection, unsupported sport filtering, and event pattern requirements.
                      </p>
                    </div>
                  </label>

                  {/* Inclusion Pattern */}
                  <div className="space-y-2">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <Checkbox
                        checked={formData.stream_include_regex_enabled || false}
                        onCheckedChange={() =>
                          setFormData({ ...formData, stream_include_regex_enabled: !formData.stream_include_regex_enabled })
                        }
                      />
                      <span className="text-sm font-normal">Inclusion Pattern</span>
                    </label>
                    <Input
                      value={formData.stream_include_regex || ""}
                      onChange={(e) =>
                        setFormData({ ...formData, stream_include_regex: e.target.value || null })
                      }
                      placeholder="e.g., Gonzaga|Washington State|Eastern Washington"
                      disabled={!formData.stream_include_regex_enabled}
                      className={cn("font-mono text-sm", !formData.stream_include_regex_enabled && "opacity-50")}
                    />
                    <p className="text-xs text-muted-foreground">
                      Only streams matching this pattern will be processed.
                    </p>
                  </div>

                  {/* Exclusion Pattern */}
                  <div className="space-y-2">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <Checkbox
                        checked={formData.stream_exclude_regex_enabled || false}
                        onCheckedChange={() =>
                          setFormData({ ...formData, stream_exclude_regex_enabled: !formData.stream_exclude_regex_enabled })
                        }
                      />
                      <span className="text-sm font-normal">Exclusion Pattern</span>
                    </label>
                    <Input
                      value={formData.stream_exclude_regex || ""}
                      onChange={(e) =>
                        setFormData({ ...formData, stream_exclude_regex: e.target.value || null })
                      }
                      placeholder="e.g., \(ES\)|\(ALT\)|All.?Star"
                      disabled={!formData.stream_exclude_regex_enabled}
                      className={cn("font-mono text-sm", !formData.stream_exclude_regex_enabled && "opacity-50")}
                    />
                    <p className="text-xs text-muted-foreground">
                      Streams matching this pattern will be excluded.
                    </p>
                  </div>
                </div>

                {/* Extraction Patterns by Event Type */}
                <div className="space-y-4">
                  <div className="border-b pb-2">
                    <h4 className="font-medium text-sm">Extraction Patterns</h4>
                    <p className="text-xs text-muted-foreground mt-1">
                      Configure custom extraction patterns by event type. Each type has its own pipeline.
                    </p>
                  </div>

                  {/* Event Type Tabs */}
                  <div className="flex gap-1 p-1 bg-muted rounded-lg">
                    <button
                      type="button"
                      onClick={() => setRegexEventType("team_vs_team")}
                      className={cn(
                        "flex-1 px-3 py-1.5 text-sm rounded-md transition-colors",
                        regexEventType === "team_vs_team"
                          ? "bg-background shadow text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Team vs Team
                    </button>
                    <button
                      type="button"
                      onClick={() => setRegexEventType("event_card")}
                      className={cn(
                        "flex-1 px-3 py-1.5 text-sm rounded-md transition-colors",
                        regexEventType === "event_card"
                          ? "bg-background shadow text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Combat / Event Card
                    </button>
                  </div>

                  {/* Team vs Team Patterns */}
                  {regexEventType === "team_vs_team" && (
                    <div className="space-y-4">
                      <p className="text-xs text-muted-foreground border-l-2 border-muted pl-3">
                        Patterns for team sports (NFL, NBA, NHL, Soccer, etc.) with "Team A vs Team B" format.
                      </p>

                      {/* Teams Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_teams_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_teams_enabled: !formData.custom_regex_teams_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Teams Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_teams || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_teams: e.target.value || null })
                          }
                          placeholder="(?<team1>[A-Z]{2,3})\s*[@vs]+\s*(?<team2>[A-Z]{2,3})"
                          disabled={!formData.custom_regex_teams_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_teams_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named groups: (?&lt;team1&gt;...) and (?&lt;team2&gt;...)
                        </p>
                      </div>

                      {/* Date Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_date_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_date_enabled: !formData.custom_regex_date_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Date Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_date || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_date: e.target.value || null })
                          }
                          placeholder="(?<date>\d{1,2}/\d{1,2})"
                          disabled={!formData.custom_regex_date_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_date_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;date&gt;...)
                        </p>

                        {/* Month/Day sub-options */}
                        <div className="ml-6 pl-3 border-l border-border/50 space-y-2">
                          <p className="text-xs text-muted-foreground">Or extract month and day separately:</p>
                          <div className="space-y-1">
                            <label className="flex items-center gap-3 cursor-pointer">
                              <Checkbox
                                checked={formData.custom_regex_month_enabled || false}
                                onCheckedChange={() =>
                                  setFormData({ ...formData, custom_regex_month_enabled: !formData.custom_regex_month_enabled })
                                }
                              />
                              <span className="text-sm font-normal">Month</span>
                            </label>
                            <Input
                              value={formData.custom_regex_month || ""}
                              onChange={(e) =>
                                setFormData({ ...formData, custom_regex_month: e.target.value || null })
                              }
                              placeholder="(?<month>\w+)"
                              disabled={!formData.custom_regex_month_enabled}
                              className={cn("font-mono text-sm", !formData.custom_regex_month_enabled && "opacity-50")}
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="flex items-center gap-3 cursor-pointer">
                              <Checkbox
                                checked={formData.custom_regex_day_enabled || false}
                                onCheckedChange={() =>
                                  setFormData({ ...formData, custom_regex_day_enabled: !formData.custom_regex_day_enabled })
                                }
                              />
                              <span className="text-sm font-normal">Day</span>
                            </label>
                            <Input
                              value={formData.custom_regex_day || ""}
                              onChange={(e) =>
                                setFormData({ ...formData, custom_regex_day: e.target.value || null })
                              }
                              placeholder="(?<day>\d{1,2})"
                              disabled={!formData.custom_regex_day_enabled}
                              className={cn("font-mono text-sm", !formData.custom_regex_day_enabled && "opacity-50")}
                            />
                          </div>
                        </div>
                      </div>

                      {/* Time Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_time_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_time_enabled: !formData.custom_regex_time_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Time Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_time || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_time: e.target.value || null })
                          }
                          placeholder="(?<time>\d{1,2}:\d{2}\s*(?:AM|PM)?)"
                          disabled={!formData.custom_regex_time_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_time_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;time&gt;...)
                        </p>
                      </div>

                      {/* League Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_league_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_league_enabled: !formData.custom_regex_league_enabled })
                            }
                          />
                          <span className="text-sm font-normal">League Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_league || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_league: e.target.value || null })
                          }
                          placeholder="(?<league>NHL|NBA|NFL|MLB)"
                          disabled={!formData.custom_regex_league_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_league_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;league&gt;...)
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Event Card Patterns (UFC, Boxing, MMA) */}
                  {regexEventType === "event_card" && (
                    <div className="space-y-4">
                      <p className="text-xs text-muted-foreground border-l-2 border-muted pl-3">
                        Patterns for combat sports (UFC, Boxing, MMA) with event card format.
                      </p>

                      {/* Fighters Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_fighters_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_fighters_enabled: !formData.custom_regex_fighters_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Fighters Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_fighters || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_fighters: e.target.value || null })
                          }
                          placeholder="(?<fighter1>\w+)\s+vs\.?\s+(?<fighter2>\w+)"
                          disabled={!formData.custom_regex_fighters_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_fighters_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named groups: (?&lt;fighter1&gt;...) and (?&lt;fighter2&gt;...)
                        </p>
                      </div>

                      {/* Event Name Pattern */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_event_name_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_event_name_enabled: !formData.custom_regex_event_name_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Event Name Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_event_name || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_event_name: e.target.value || null })
                          }
                          placeholder="(?<event_name>UFC\s*\d+|Bellator\s*\d+)"
                          disabled={!formData.custom_regex_event_name_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_event_name_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;event_name&gt;...)
                        </p>
                      </div>

                      {/* Date Pattern (shared) */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_date_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_date_enabled: !formData.custom_regex_date_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Date Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_date || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_date: e.target.value || null })
                          }
                          placeholder="(?<date>\d{1,2}/\d{1,2})"
                          disabled={!formData.custom_regex_date_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_date_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;date&gt;...)
                        </p>

                        {/* Month/Day sub-options */}
                        <div className="ml-6 pl-3 border-l border-border/50 space-y-2">
                          <p className="text-xs text-muted-foreground">Or extract month and day separately:</p>
                          <div className="space-y-1">
                            <label className="flex items-center gap-3 cursor-pointer">
                              <Checkbox
                                checked={formData.custom_regex_month_enabled || false}
                                onCheckedChange={() =>
                                  setFormData({ ...formData, custom_regex_month_enabled: !formData.custom_regex_month_enabled })
                                }
                              />
                              <span className="text-sm font-normal">Month</span>
                            </label>
                            <Input
                              value={formData.custom_regex_month || ""}
                              onChange={(e) =>
                                setFormData({ ...formData, custom_regex_month: e.target.value || null })
                              }
                              placeholder="(?<month>\w+)"
                              disabled={!formData.custom_regex_month_enabled}
                              className={cn("font-mono text-sm", !formData.custom_regex_month_enabled && "opacity-50")}
                            />
                          </div>
                          <div className="space-y-1">
                            <label className="flex items-center gap-3 cursor-pointer">
                              <Checkbox
                                checked={formData.custom_regex_day_enabled || false}
                                onCheckedChange={() =>
                                  setFormData({ ...formData, custom_regex_day_enabled: !formData.custom_regex_day_enabled })
                                }
                              />
                              <span className="text-sm font-normal">Day</span>
                            </label>
                            <Input
                              value={formData.custom_regex_day || ""}
                              onChange={(e) =>
                                setFormData({ ...formData, custom_regex_day: e.target.value || null })
                              }
                              placeholder="(?<day>\d{1,2})"
                              disabled={!formData.custom_regex_day_enabled}
                              className={cn("font-mono text-sm", !formData.custom_regex_day_enabled && "opacity-50")}
                            />
                          </div>
                        </div>
                      </div>

                      {/* Time Pattern (shared) */}
                      <div className="space-y-2">
                        <label className="flex items-center gap-3 cursor-pointer">
                          <Checkbox
                            checked={formData.custom_regex_time_enabled || false}
                            onCheckedChange={() =>
                              setFormData({ ...formData, custom_regex_time_enabled: !formData.custom_regex_time_enabled })
                            }
                          />
                          <span className="text-sm font-normal">Time Pattern</span>
                        </label>
                        <Input
                          value={formData.custom_regex_time || ""}
                          onChange={(e) =>
                            setFormData({ ...formData, custom_regex_time: e.target.value || null })
                          }
                          placeholder="(?<time>\d{1,2}:\d{2}\s*(?:AM|PM)?)"
                          disabled={!formData.custom_regex_time_enabled}
                          className={cn("font-mono text-sm", !formData.custom_regex_time_enabled && "opacity-50")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Use named group: (?&lt;time&gt;...)
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
          </CollapsibleSection>

          {/* Stream Timezone */}
          <CollapsibleSection title="Stream Timezone" defaultCollapsed persistKey="sources-form.timezone">
              <StreamTimezoneSelector
                value={formData.stream_timezone ?? null}
                onChange={(tz) => setFormData({ ...formData, stream_timezone: tz })}
              />
              <p className="text-xs text-muted-foreground mt-2">
                Optional. Timezone markers (e.g., "ET", "PT") are auto-detected. Set this only if your provider omits them and uses a different timezone than yours.
              </p>
          </CollapsibleSection>

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => navigate("/sources")}>
              Cancel
            </Button>
            <SaveButton onClick={() => handleSubmit()} pending={isPending}>
              {isEdit ? "Update Stream Source" : "Create Stream Source"}
            </SaveButton>
          </div>
        </div>

      {/* Test Patterns Modal — bidirectional sync with form regex fields */}
      <TestPatternsModal
        open={testPatternsOpen}
        onOpenChange={setTestPatternsOpen}
        groupId={isEdit ? Number(groupId) : null}
        initialPatterns={currentPatterns}
        onApply={handlePatternsApply}
      />
    </div>
  )
}
