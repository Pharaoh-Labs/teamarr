import { useState, useMemo } from "react"
import { useQuery, useQueries } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import { conferenceLabel, useConferenceFilter } from "@/hooks/useConferenceFilter"
import { getLeagueTeams, getTeamPickerLeagues, type CachedTeam } from "@/api/teams"
import { SelectedBadges } from "@/components/ui/selected-badges"
import type { TeamFilterEntry } from "@/api/types"

interface TeamPickerProps {
  leagues: string[]
  selectedTeams: TeamFilterEntry[]
  onSelectionChange: (teams: TeamFilterEntry[]) => void
  placeholder?: string
  singleSelect?: boolean
}

interface SportGroup {
  sport: string
  sport_display_name: string
  leagues: LeagueGroup[]
}

interface LeagueGroup {
  league: string
  sport: string
  teams: CachedTeam[]
}

interface LeagueSectionProps {
  lg: LeagueGroup
  isExpanded: boolean
  singleSelect: boolean
  onToggle: () => void
  isTeamSelected: (team: CachedTeam) => boolean
  onToggleTeam: (team: CachedTeam) => void
  onSelectAll: (teams: CachedTeam[]) => void
  onClear: (league: string) => void
  selectedCount: number
}

/**
 * One league row: header, optional conference filter, team checkboxes.
 *
 * Split out so each league instance can own its own conference query (#91) —
 * hooks can't run in a loop — which also makes the fetch lazy: conferences
 * load only for leagues the user actually expands.
 */
function LeagueSection({
  lg,
  isExpanded,
  singleSelect,
  onToggle,
  isTeamSelected,
  onToggleTeam,
  onSelectAll,
  onClear,
  selectedCount,
}: LeagueSectionProps) {
  const { conferences, selectedConference, setSelectedConference, conferenceTeamIds } =
    useConferenceFilter(isExpanded ? lg.league : null)

  // Conference filter narrows both the visible list and what Select All takes,
  // so "SEC + Select All" adds exactly that conference (#91).
  const visibleTeams = conferenceTeamIds
    ? lg.teams.filter((t) => conferenceTeamIds.has(t.provider_team_id))
    : lg.teams

  return (
    <div className="border-b last:border-b-0">
      {/* League header — actions as siblings, not nested (5hq.16) */}
      <div className="flex items-center justify-between p-2 hover:bg-muted/50 text-sm">
        <button onClick={onToggle} className="flex-1 flex items-center gap-2 text-left">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
          <span className="uppercase text-xs font-medium">{lg.league}</span>
          <span className="text-muted-foreground font-normal text-xs">
            ({selectedCount} of {visibleTeams.length})
          </span>
        </button>
        {!singleSelect && (
          <div className="flex gap-2 text-xs">
            <button
              onClick={() => onSelectAll(visibleTeams)}
              className="text-primary hover:underline"
            >
              Select All
            </button>
            <button
              onClick={() => onClear(lg.league)}
              className="text-muted-foreground hover:underline"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {isExpanded && (
        <div className="px-2 pb-2 space-y-1 ml-4">
          {conferences.length > 0 && (
            <Select
              value={selectedConference}
              onChange={(e) => setSelectedConference(e.target.value)}
              className="w-full h-8 text-xs my-1"
              aria-label={`Filter ${lg.league} by conference`}
            >
              <option value="">All conferences</option>
              {conferences.map((conf) => (
                <option key={conf.key} value={conf.key}>
                  {conferenceLabel(conf)}
                </option>
              ))}
            </Select>
          )}
          {visibleTeams.map((team) => (
            <label
              key={`${team.provider}-${team.provider_team_id}`}
              className="flex items-center gap-2 p-1.5 rounded hover:bg-muted/50 cursor-pointer"
            >
              <Checkbox
                checked={isTeamSelected(team)}
                onCheckedChange={() => onToggleTeam(team)}
              />
              {team.logo_url && (
                <img
                  src={team.logo_url}
                  alt=""
                  className="h-5 w-5 object-contain"
                  onError={(e) => {
                    ;(e.target as HTMLImageElement).style.display = "none"
                  }}
                />
              )}
              <span className="text-sm">{team.team_name}</span>
              {team.team_abbrev && (
                <span className="text-xs text-muted-foreground">({team.team_abbrev})</span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function TeamPicker({
  leagues,
  selectedTeams,
  onSelectionChange,
  placeholder = "Search teams...",
  singleSelect = false,
}: TeamPickerProps) {
  const [search, setSearch] = useState("")
  const [expandedSports, setExpandedSports] = useState<Set<string>>(new Set())
  const [expandedLeagues, setExpandedLeagues] = useState<Set<string>>(new Set())

  // Fetch all leagues with their sports from team_cache (source of truth)
  const leagueInfoQuery = useQuery({
    queryKey: ["teamPickerLeagues"],
    queryFn: getTeamPickerLeagues,
    staleTime: 5 * 60 * 1000,
  })

  // Create lookup map: league slug -> { sport, sport_display_name, is_configured, name }
  const leagueLookup = useMemo(() => {
    const map = new Map<string, { sport: string; sport_display_name: string; is_configured: boolean; name: string }>()
    if (leagueInfoQuery.data?.leagues) {
      for (const lg of leagueInfoQuery.data.leagues) {
        map.set(lg.slug, {
          sport: lg.sport,
          sport_display_name: lg.sport_display_name,
          is_configured: lg.is_configured,
          name: lg.name,
        })
      }
    }
    return map
  }, [leagueInfoQuery.data])

  // Fetch teams for all leagues
  const teamQueries = useQueries({
    queries: leagues.map((league) => ({
      queryKey: ["leagueTeams", league],
      queryFn: () => getLeagueTeams(league),
      staleTime: 5 * 60 * 1000, // 5 minutes
      enabled: leagues.length > 0,
    })),
  })

  const isLoading = teamQueries.some((q) => q.isLoading) || leagueInfoQuery.isLoading

  // Group teams by sport, then by league
  // Uses leagueLookup for sport (no "Other" fallback needed since data comes from team_cache)
  const teamsBySport = useMemo(() => {
    const sportMap = new Map<string, { display_name: string; leagues: Map<string, { teams: CachedTeam[]; is_configured: boolean; name: string }> }>()

    leagues.forEach((league, index) => {
      const query = teamQueries[index]
      if (query.data && query.data.length > 0) {
        // Get sport from lookup (source of truth), fall back to first team's sport if not found
        const leagueInfo = leagueLookup.get(league)
        const sport = leagueInfo?.sport ?? query.data[0]?.sport ?? "unknown"
        const sportDisplayName = leagueInfo?.sport_display_name ?? sport

        if (!sportMap.has(sport)) {
          sportMap.set(sport, { display_name: sportDisplayName, leagues: new Map() })
        }
        const sportData = sportMap.get(sport)!
        sportData.leagues.set(league, {
          teams: query.data,
          is_configured: leagueInfo?.is_configured ?? false,
          name: leagueInfo?.name ?? league.toUpperCase(),
        })
      }
    })

    // Convert to array structure
    // Sort: by sport display name, within each sport: configured leagues first, then alphabetically
    const result: SportGroup[] = []
    const sortedSports = Array.from(sportMap.entries()).sort((a, b) =>
      a[1].display_name.localeCompare(b[1].display_name)
    )

    for (const [sport, sportData] of sortedSports) {
      const leagueGroups: LeagueGroup[] = []

      // Sort leagues: configured first, then by name
      const sortedLeagues = Array.from(sportData.leagues.entries()).sort((a, b) => {
        // Configured leagues first
        if (a[1].is_configured !== b[1].is_configured) {
          return a[1].is_configured ? -1 : 1
        }
        // Then alphabetically by name
        return a[1].name.localeCompare(b[1].name)
      })

      for (const [league, data] of sortedLeagues) {
        leagueGroups.push({
          league,
          sport,
          teams: data.teams,
        })
      }

      result.push({
        sport,
        sport_display_name: sportData.display_name,
        leagues: leagueGroups,
      })
    }

    return result
  }, [leagues, teamQueries, leagueLookup])

  // Filter teams by search
  const filteredBySport = useMemo(() => {
    if (!search.trim()) return teamsBySport
    const searchLower = search.toLowerCase()

    return teamsBySport
      .map((sportGroup) => ({
        ...sportGroup,
        leagues: sportGroup.leagues
          .map((lg) => ({
            ...lg,
            teams: lg.teams.filter(
              (t) =>
                t.team_name.toLowerCase().includes(searchLower) ||
                (t.team_abbrev && t.team_abbrev.toLowerCase().includes(searchLower)) ||
                (t.team_short_name && t.team_short_name.toLowerCase().includes(searchLower))
            ),
          }))
          .filter((lg) => lg.teams.length > 0),
      }))
      .filter((sg) => sg.leagues.length > 0)
  }, [teamsBySport, search])

  // When searching, auto-expand all filtered results
  const isSearching = search.trim().length > 0
  const isSportExpanded = (sport: string) => isSearching || expandedSports.has(sport)
  const isLeagueExpanded = (league: string) => isSearching || expandedLeagues.has(league)

  // Toggle sport expansion
  const toggleSport = (sport: string) => {
    setExpandedSports((prev) => {
      const next = new Set(prev)
      if (next.has(sport)) {
        next.delete(sport)
      } else {
        next.add(sport)
      }
      return next
    })
  }

  // Toggle league expansion
  const toggleLeague = (league: string) => {
    setExpandedLeagues((prev) => {
      const next = new Set(prev)
      if (next.has(league)) {
        next.delete(league)
      } else {
        next.add(league)
      }
      return next
    })
  }

  // Check if team is selected
  const isTeamSelected = (team: CachedTeam) => {
    return selectedTeams.some(
      (t) => t.provider === team.provider && t.team_id === team.provider_team_id && t.league === team.league
    )
  }

  // Toggle team selection
  const toggleTeam = (team: CachedTeam) => {
    if (singleSelect) {
      const isSelected = isTeamSelected(team)
      if (isSelected) {
        onSelectionChange([])
      } else {
        onSelectionChange([{
          provider: team.provider,
          team_id: team.provider_team_id,
          league: team.league,
          name: team.team_name,
        }])
      }
    } else {
      const isSelected = isTeamSelected(team)
      if (isSelected) {
        onSelectionChange(
          selectedTeams.filter(
            (t) => !(t.provider === team.provider && t.team_id === team.provider_team_id && t.league === team.league)
          )
        )
      } else {
        onSelectionChange([
          ...selectedTeams,
          {
            provider: team.provider,
            team_id: team.provider_team_id,
            league: team.league,
            name: team.team_name,
          },
        ])
      }
    }
  }

  // Remove selected team
  const removeTeam = (team: TeamFilterEntry) => {
    onSelectionChange(
      selectedTeams.filter(
        (t) => !(t.provider === team.provider && t.team_id === team.team_id && t.league === team.league)
      )
    )
  }

  // Select all teams in a league
  const selectAllInLeague = (teams: CachedTeam[]) => {
    const newTeams = teams.filter((t) => !isTeamSelected(t)).map((t) => ({
      provider: t.provider,
      team_id: t.provider_team_id,
      league: t.league,
      name: t.team_name,
    }))
    onSelectionChange([...selectedTeams, ...newTeams])
  }

  // Clear all teams in a league
  const clearLeague = (league: string) => {
    onSelectionChange(selectedTeams.filter((t) => t.league !== league))
  }

  // Select all teams in a sport
  const selectAllInSport = (sportGroup: SportGroup) => {
    const allTeams = sportGroup.leagues.flatMap((lg) => lg.teams)
    const newTeams = allTeams.filter((t) => !isTeamSelected(t)).map((t) => ({
      provider: t.provider,
      team_id: t.provider_team_id,
      league: t.league,
      name: t.team_name,
    }))
    onSelectionChange([...selectedTeams, ...newTeams])
  }

  // Clear all teams in a sport
  const clearSport = (sportGroup: SportGroup) => {
    const sportLeagues = new Set(sportGroup.leagues.map((lg) => lg.league))
    onSelectionChange(selectedTeams.filter((t) => !sportLeagues.has(t.league)))
  }

  // Count selected in league
  const countSelectedInLeague = (league: string) => {
    return selectedTeams.filter((t) => t.league === league).length
  }

  // Count selected in sport
  const countSelectedInSport = (sportGroup: SportGroup) => {
    const sportLeagues = new Set(sportGroup.leagues.map((lg) => lg.league))
    return selectedTeams.filter((t) => sportLeagues.has(t.league)).length
  }

  if (leagues.length === 0) {
    return (
      <div className="text-sm text-muted-foreground p-4 border rounded-md">
        Select leagues first to enable team filtering.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Selected teams badges */}
      <SelectedBadges
        items={selectedTeams.map((team) => ({
          key: `${team.provider}-${team.team_id}`,
          label: team.name || team.team_id,
        }))}
        onRemove={(key) => {
          const team = selectedTeams.find(t => `${t.provider}-${t.team_id}` === key)
          if (team) removeTeam(team)
        }}
      />

      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={placeholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-8"
        />
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="text-sm text-muted-foreground p-4 text-center">
          Loading teams...
        </div>
      )}

      {/* Team list by sport, then league */}
      <div className="border rounded-md max-h-80 overflow-y-auto">
        {filteredBySport.map((sportGroup) => (
          <div key={sportGroup.sport} className="border-b last:border-b-0">
            {/* Sport header — actions are SIBLINGS of the toggle button, never
                nested (invalid <button><button> HTML, 5hq.16) */}
            <div className="flex items-center justify-between p-2 hover:bg-muted/50 text-sm font-medium bg-muted/30">
              <button
                onClick={() => toggleSport(sportGroup.sport)}
                className="flex-1 flex items-center gap-2 text-left"
              >
                {isSportExpanded(sportGroup.sport) ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                <span>{sportGroup.sport_display_name}</span>
                <span className="text-muted-foreground font-normal text-xs">
                  ({countSelectedInSport(sportGroup)} selected)
                </span>
              </button>
              {!singleSelect && (
                <div className="flex gap-2 text-xs">
                  <button
                    onClick={() => selectAllInSport(sportGroup)}
                    className="text-primary hover:underline"
                  >
                    Select All
                  </button>
                  <button
                    onClick={() => clearSport(sportGroup)}
                    className="text-muted-foreground hover:underline"
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>

            {/* Leagues within sport */}
            {isSportExpanded(sportGroup.sport) && (
              <div className="ml-4">
                {sportGroup.leagues.map((lg) => (
                  <LeagueSection
                    key={lg.league}
                    lg={lg}
                    isExpanded={isLeagueExpanded(lg.league)}
                    singleSelect={singleSelect}
                    onToggle={() => toggleLeague(lg.league)}
                    isTeamSelected={isTeamSelected}
                    onToggleTeam={toggleTeam}
                    onSelectAll={selectAllInLeague}
                    onClear={clearLeague}
                    selectedCount={countSelectedInLeague(lg.league)}
                  />
                ))}
              </div>
            )}
          </div>
        ))}

        {/* No results */}
        {filteredBySport.length === 0 && !isLoading && (
          <div className="text-sm text-muted-foreground p-4 text-center">
            {search ? "No teams match your search." : "No teams available."}
          </div>
        )}
      </div>
    </div>
  )
}
