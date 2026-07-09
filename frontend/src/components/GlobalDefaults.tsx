/**
 * GlobalDefaults — global sports/league subscription + team filter management.
 *
 * Rendered inside the Subscriptions page tile sub-nav. Stays mounted across the
 * "sportleague" / "soccer" / "teams" tiles so the shared subscription state is
 * preserved, rendering only the section matching the active tile. Manages:
 * - Non-soccer league selection (via LeaguePicker)
 * - Soccer configuration (via SoccerModeSelector)
 * - Default team filter (include/exclude teams, playoff bypass)
 *
 * Explicit Save buttons — league changes trigger EPG regeneration.
 */

import { useState, useMemo, useCallback } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Loader2 } from "lucide-react"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { LeaguePicker } from "@/components/LeaguePicker"
import { SoccerModeSelector, type SoccerMode } from "@/components/SoccerModeSelector"
import { TeamPicker } from "@/components/TeamPicker"
import { useSubscription, useUpdateSubscription } from "@/hooks/useSubscription"
import { useTeamFilterSettings, useUpdateTeamFilterSettings } from "@/hooks/useSettings"
import { getLeagues } from "@/api/teams"
import type { SoccerFollowedTeam } from "@/api/types"
import type { TeamFilterSettings } from "@/api/settings"

/**
 * Split subscribed league slugs into soccer vs non-soccer. Module-level so the
 * render-time seeding block below stays simple enough for the React Compiler
 * (a .find() lambda combined with a method call inside that block defeats its
 * memoization analysis).
 */
function splitSubscribedLeagues(
  slugs: string[],
  allLeagues: { slug: string; sport?: string | null }[],
): { soccer: string[]; nonSoccer: string[] } {
  const soccer: string[] = []
  const nonSoccer: string[] = []
  for (const slug of slugs) {
    const league = allLeagues.find((l) => l.slug === slug)
    if (league?.sport?.toLowerCase() === "soccer") {
      soccer.push(slug)
    } else {
      nonSoccer.push(slug)
    }
  }
  return { soccer, nonSoccer }
}

export function GlobalDefaults({
  activeTile,
}: {
  activeTile: "sportleague" | "soccer" | "teams"
}) {
  // Fetch subscription state from server
  const { data: subscription, isLoading: subLoading } = useSubscription()
  const updateMutation = useUpdateSubscription()

  // Fetch leagues for sport counting
  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
  })
  const allLeagues = leaguesData?.leagues || []

  // Team filter settings
  const { data: teamFilterData } = useTeamFilterSettings()
  const updateTeamFilter = useUpdateTeamFilterSettings()

  // Local state for editing (synced from subscription on load)
  const [nonSoccerLeagues, setNonSoccerLeagues] = useState<string[]>([])
  const [soccerMode, setSoccerMode] = useState<SoccerMode>(null)
  const [soccerLeagues, setSoccerLeagues] = useState<string[]>([])
  const [followedTeams, setFollowedTeams] = useState<SoccerFollowedTeam[]>([])
  const [hasLocalChanges, setHasLocalChanges] = useState(false)

  // Team filter local state
  const [teamFilter, setTeamFilter] = useState<TeamFilterSettings>({
    enabled: true,
    include_teams: null,
    exclude_teams: null,
    mode: "include",
    bypass_filter_for_playoffs: false,
  })

  // Sync local state from the server subscription during render (React's
  // "adjusting state when a prop changes" pattern) — re-seeds whenever the
  // subscription or the league list refetches, exactly like the previous
  // effect, without the extra effect render pass.
  const [syncedSubscription, setSyncedSubscription] = useState<{
    subscription: typeof subscription
    leaguesData: typeof leaguesData
  } | null>(null)
  if (
    subscription &&
    (syncedSubscription?.subscription !== subscription ||
      syncedSubscription?.leaguesData !== leaguesData)
  ) {
    setSyncedSubscription({ subscription, leaguesData })

    // Split leagues into soccer vs non-soccer
    const { soccer, nonSoccer } = splitSubscribedLeagues(subscription.leagues, allLeagues)

    setNonSoccerLeagues(nonSoccer)
    setSoccerLeagues(soccer)
    setSoccerMode(subscription.soccer_mode as SoccerMode)
    setFollowedTeams(subscription.soccer_followed_teams || [])
    setHasLocalChanges(false)
  }

  // Sync team filter state from server data during render (same pattern) —
  // re-seeds on every refetch, exactly like the previous effect.
  const [syncedTeamFilterData, setSyncedTeamFilterData] = useState<typeof teamFilterData>(undefined)
  if (teamFilterData && teamFilterData !== syncedTeamFilterData) {
    setSyncedTeamFilterData(teamFilterData)
    setTeamFilter(teamFilterData)
  }

  // Combined leagues for team picker
  const allSubscribedLeagues = useMemo(
    () => [...nonSoccerLeagues, ...soccerLeagues],
    [nonSoccerLeagues, soccerLeagues]
  )

  // Handle non-soccer league change
  const handleNonSoccerChange = useCallback((leagues: string[]) => {
    setNonSoccerLeagues(leagues)
    setHasLocalChanges(true)
  }, [])

  // Handle soccer league change
  const handleSoccerLeaguesChange = useCallback((leagues: string[]) => {
    setSoccerLeagues(leagues)
    setHasLocalChanges(true)
  }, [])

  // Handle soccer mode change
  const handleSoccerModeChange = useCallback((mode: SoccerMode) => {
    setSoccerMode(mode)
    setHasLocalChanges(true)
  }, [])

  // Handle followed teams change
  const handleFollowedTeamsChange = useCallback((teams: SoccerFollowedTeam[]) => {
    setFollowedTeams(teams)
    setHasLocalChanges(true)
  }, [])

  // Save subscription to server
  const handleSave = useCallback(() => {
    const combinedLeagues = [...nonSoccerLeagues, ...soccerLeagues]
    updateMutation.mutate(
      {
        leagues: combinedLeagues,
        soccer_mode: soccerMode,
        soccer_followed_teams: followedTeams.length > 0 ? followedTeams : null,
      },
      {
        onSuccess: () => {
          setHasLocalChanges(false)
          toast.success("Subscribed sports updated")
        },
        onError: () => {
          toast.error("Failed to update subscribed sports")
        },
      }
    )
  }, [nonSoccerLeagues, soccerLeagues, soccerMode, followedTeams, updateMutation])

  // Save team filter
  const handleSaveTeamFilter = useCallback(() => {
    updateTeamFilter.mutate({
      enabled: teamFilter.enabled,
      include_teams: teamFilter.include_teams,
      exclude_teams: teamFilter.exclude_teams,
      mode: teamFilter.mode,
      clear_include_teams: teamFilter.mode === "exclude" || !teamFilter.include_teams?.length,
      clear_exclude_teams: teamFilter.mode === "include" || !teamFilter.exclude_teams?.length,
      bypass_filter_for_playoffs: teamFilter.bypass_filter_for_playoffs,
    }, {
      onSuccess: () => toast.success("Default team filter saved"),
      onError: () => toast.error("Failed to save team filter"),
    })
  }, [teamFilter, updateTeamFilter])

  if (subLoading || !leaguesData) {
    return (
      <Card>
        <CardContent>
          <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading subscriptions…
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      {/* ── Tile: Sport / League ── */}
      {activeTile === "sportleague" && (
        <Card className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <Label className="text-base font-medium">Sports (Non-Soccer)</Label>
            {hasLocalChanges && (
              <span className="text-xs text-amber-500 font-medium">Unsaved changes</span>
            )}
          </div>
          <LeaguePicker
            selectedLeagues={nonSoccerLeagues}
            onSelectionChange={handleNonSoccerChange}
            excludeSport="soccer"
            maxHeight="max-h-[60vh]"
            showSearch={true}
            showSelectedBadges={true}
            maxBadges={10}
          />
          <div className="flex justify-end pt-2">
            <SaveButton
              onClick={handleSave}
              pending={updateMutation.isPending}
              disabled={!hasLocalChanges}
            />
          </div>
        </Card>
      )}

      {/* ── Tile: Soccer ── */}
      {activeTile === "soccer" && (
        <Card className="p-4 space-y-4">
          <div className="flex items-center justify-between">
            <Label className="text-base font-medium">Soccer Leagues</Label>
            {hasLocalChanges && (
              <span className="text-xs text-amber-500 font-medium">Unsaved changes</span>
            )}
          </div>
          <SoccerModeSelector
            mode={soccerMode}
            onModeChange={handleSoccerModeChange}
            selectedLeagues={soccerLeagues}
            onLeaguesChange={handleSoccerLeaguesChange}
            followedTeams={followedTeams}
            onFollowedTeamsChange={handleFollowedTeamsChange}
          />
          <div className="flex justify-end pt-2">
            <SaveButton
              onClick={handleSave}
              pending={updateMutation.isPending}
              disabled={!hasLocalChanges}
            />
          </div>
        </Card>
      )}

      {/* ── Tile: Teams (Default Team Filter) ── */}
      {activeTile === "teams" && (
            <Card className="p-4 space-y-4">
              <div className="flex items-center justify-between">
                <Label className="text-base font-medium">Default Team Filter</Label>
                <div className="flex items-center gap-2">
                  <Label htmlFor="team-filter-enabled" className="text-sm">
                    {teamFilter.enabled ? "Enabled" : "Disabled"}
                  </Label>
                  <Switch
                    id="team-filter-enabled"
                    checked={teamFilter.enabled}
                    onCheckedChange={(checked) => {
                      setTeamFilter({ ...teamFilter, enabled: checked })
                    }}
                  />
                </div>
              </div>

              {/* Mode selector */}
              <div className="flex items-center gap-4">
                <Label>Filter Mode:</Label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="default-team-filter-mode"
                      value="include"
                      checked={teamFilter.mode === "include"}
                      onChange={() => setTeamFilter({ ...teamFilter, mode: "include" })}
                      className="accent-primary"
                    />
                    <span className="text-sm">Include only selected teams</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="default-team-filter-mode"
                      value="exclude"
                      checked={teamFilter.mode === "exclude"}
                      onChange={() => setTeamFilter({ ...teamFilter, mode: "exclude" })}
                      className="accent-primary"
                    />
                    <span className="text-sm">Exclude selected teams</span>
                  </label>
                </div>
              </div>

              {/* TeamPicker */}
              <TeamPicker
                leagues={allSubscribedLeagues}
                selectedTeams={
                  teamFilter.mode === "include"
                    ? (teamFilter.include_teams ?? [])
                    : (teamFilter.exclude_teams ?? [])
                }
                onSelectionChange={(teams) => {
                  if (teamFilter.mode === "include") {
                    setTeamFilter({ ...teamFilter, include_teams: teams, exclude_teams: [] })
                  } else {
                    setTeamFilter({ ...teamFilter, exclude_teams: teams, include_teams: [] })
                  }
                }}
                placeholder="Search teams to add to default filter..."
              />

              {/* Playoff bypass option */}
              <label className="flex items-center gap-2 cursor-pointer py-2">
                <Checkbox
                  checked={teamFilter.bypass_filter_for_playoffs}
                  onCheckedChange={(checked) =>
                    setTeamFilter({ ...teamFilter, bypass_filter_for_playoffs: !!checked })
                  }
                />
                <span className="text-sm">
                  Include all playoff games (bypass team filter for postseason events)
                </span>
              </label>

              {/* Status message and Save button */}
              <div className="flex justify-between items-center">
                <p className="text-xs text-muted-foreground">
                  {!teamFilter.enabled
                    ? "Team filtering is disabled. All events will be matched."
                    : !(teamFilter.include_teams?.length || teamFilter.exclude_teams?.length)
                      ? "No teams selected. All events will be matched."
                      : teamFilter.mode === "include"
                        ? `Only events involving ${teamFilter.include_teams?.length} selected team(s) will be matched.`
                        : `Events involving ${teamFilter.exclude_teams?.length} selected team(s) will be excluded.`}
                </p>
                <SaveButton
                  onClick={handleSaveTeamFilter}
                  pending={updateTeamFilter.isPending}
                >
                  Save Team Filter
                </SaveButton>
              </div>
            </Card>
      )}
    </>
  )
}
