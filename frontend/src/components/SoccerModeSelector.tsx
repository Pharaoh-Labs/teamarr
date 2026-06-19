import { useState, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { ListChecks, Users, Info, Search, Loader2 } from "lucide-react"
import { LeaguePicker } from "@/components/LeaguePicker"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { searchTeams } from "@/api/teams"
import type { SoccerFollowedTeam } from "@/api/types"

export type SoccerMode = 'teams' | 'manual' | null

interface SoccerModeSelectorProps {
  mode: SoccerMode
  onModeChange: (mode: SoccerMode) => void
  selectedLeagues: string[]
  onLeaguesChange: (leagues: string[]) => void
  followedTeams: SoccerFollowedTeam[]
  onFollowedTeamsChange: (teams: SoccerFollowedTeam[]) => void
  className?: string
}

export function SoccerModeSelector({
  mode,
  onModeChange,
  selectedLeagues,
  onLeaguesChange,
  followedTeams,
  onFollowedTeamsChange,
  className,
}: SoccerModeSelectorProps) {
  const [searchQuery, setSearchQuery] = useState("")

  // Search for soccer teams
  const { data: searchResults, isLoading: isSearching } = useQuery({
    queryKey: ["soccer-team-search", searchQuery],
    queryFn: () => searchTeams(searchQuery, undefined, "soccer"),
    enabled: searchQuery.length >= 2,
    staleTime: 30 * 1000, // 30 seconds
  })

  const handleModeChange = (newMode: 'teams' | 'manual') => {
    // Just switch modes - preserve data so users can switch back without losing selections
    onModeChange(newMode)
  }

  const handleTeamSelect = (team: { provider: string; team_id: string; name: string }) => {
    // Check if already followed
    const exists = followedTeams.some(t => t.team_id === team.team_id && t.provider === team.provider)
    if (exists) return

    onFollowedTeamsChange([
      ...followedTeams,
      { provider: team.provider, team_id: team.team_id, name: team.name },
    ])
    setSearchQuery("") // Clear search after selection
  }

  const handleTeamRemove = (teamId: string, provider: string) => {
    onFollowedTeamsChange(
      followedTeams.filter(t => !(t.team_id === teamId && t.provider === provider))
    )
  }

  // Filter out already followed teams from search results
  const filteredResults = useMemo(() => {
    if (!searchResults?.teams) return []
    return searchResults.teams.filter(
      team => !followedTeams.some(f => f.team_id === team.team_id && f.provider === team.provider)
    )
  }, [searchResults, followedTeams])

  return (
    <div className={cn("space-y-3", className)}>
      {/* Follow Teams Mode */}
      <div>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="radio"
            name="soccer-mode"
            checked={mode === 'teams'}
            onChange={() => handleModeChange('teams')}
            className="mt-1.5 h-4 w-4 border-muted-foreground text-primary focus:ring-primary"
          />
          <div className="flex-1">
            <span className="flex items-center gap-2 font-medium">
              <Users className="h-4 w-4 text-muted-foreground" />
              Follow Teams
            </span>
            <p className="text-sm text-muted-foreground mt-1">
              Follow specific teams. Their leagues are auto-discovered (EPL, Champions League, cups, etc).
            </p>
          </div>
        </label>

        {/* Team Search - shown directly under Follow Teams when selected */}
        {mode === 'teams' && (
          <div className="pl-7 border-l-2 border-muted ml-2 mt-3 space-y-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Info className="h-4 w-4" />
            <span>
              {followedTeams.length === 0
                ? "Search and select teams to follow"
                : `Following ${followedTeams.length} team${followedTeams.length === 1 ? '' : 's'}`}
            </span>
          </div>

          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-500" />
            <span>
              Following a team adds <strong>all leagues that team could play in</strong> (its
              domestic league, cups, and continental competitions) — so you'll see every match in
              those competitions, not just this team's. To surface events for the followed teams
              only, enable the <strong>Default Team Filter</strong> in the <strong>Teams</strong> tab
              (Include mode) and select them.
            </span>
          </div>

          {/* Show followed teams */}
          {followedTeams.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {followedTeams.map((team) => (
                <span
                  key={`${team.provider}-${team.team_id}`}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-secondary text-secondary-foreground rounded-md text-sm"
                >
                  {team.name || team.team_id}
                  <button
                    type="button"
                    onClick={() => handleTeamRemove(team.team_id, team.provider)}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    &times;
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Team search input */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Search for a soccer team..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
            {isSearching && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>

          {/* Search results dropdown */}
          {searchQuery.length >= 2 && (
            <div className="border rounded-md max-h-60 overflow-y-auto">
              {isSearching ? (
                <div className="p-3 text-center text-sm text-muted-foreground">
                  Searching...
                </div>
              ) : filteredResults.length > 0 ? (
                <div className="divide-y">
                  {filteredResults.map((team) => (
                    <button
                      key={`${team.provider}-${team.team_id}`}
                      type="button"
                      onClick={() => handleTeamSelect({
                        provider: team.provider,
                        team_id: team.team_id,
                        name: team.name,
                      })}
                      className="w-full text-left px-3 py-2 hover:bg-muted/50 transition-colors"
                    >
                      <div className="font-medium">{team.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {team.league.toUpperCase()}
                      </div>
                    </button>
                  ))}
                </div>
              ) : searchResults?.teams.length === followedTeams.length ? (
                <div className="p-3 text-center text-sm text-muted-foreground">
                  All matching teams already followed
                </div>
              ) : (
                <div className="p-3 text-center text-sm text-muted-foreground">
                  No teams found
                </div>
              )}
            </div>
          )}
          </div>
        )}
      </div>

      {/* Select Leagues Mode */}
      <div>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="radio"
            name="soccer-mode"
            checked={mode === 'manual'}
            onChange={() => handleModeChange('manual')}
            className="mt-1.5 h-4 w-4 border-muted-foreground text-primary focus:ring-primary"
          />
          <div className="flex-1">
            <span className="flex items-center gap-2 font-medium">
              <ListChecks className="h-4 w-4 text-muted-foreground" />
              Select Leagues
            </span>
            <p className="text-sm text-muted-foreground mt-1">
              Choose specific leagues to include. Best for focused coverage.
            </p>
          </div>
        </label>

        {/* League Picker - shown directly under Select Leagues when selected */}
        {mode === 'manual' && (
          <div className="pl-7 border-l-2 border-muted ml-2 mt-3">
            <div className="flex items-center gap-2 mb-2 text-sm text-muted-foreground">
              <Info className="h-4 w-4" />
              <span>
                {selectedLeagues.length === 0
                  ? "Select the soccer leagues you want to include"
                  : `${selectedLeagues.length} league${selectedLeagues.length === 1 ? '' : 's'} selected`}
              </span>
            </div>
            <LeaguePicker
              selectedLeagues={selectedLeagues}
              onSelectionChange={onLeaguesChange}
              maxHeight="max-h-80"
              showSearch={true}
              maxBadges={10}
              sportFilter="soccer"
            />
          </div>
        )}
      </div>
    </div>
  )
}
