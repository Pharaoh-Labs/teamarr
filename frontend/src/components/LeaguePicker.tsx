import { useState, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { Loader2, Check, ChevronRight, ChevronDown, Crown } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { cn, getSportDisplayName, getLeagueDisplayName } from "@/lib/utils"
import { SelectedBadges, type BadgeItem } from "@/components/ui/selected-badges"
import type { CachedLeague } from "@/api/teams"
import { getLeagues, getSports } from "@/api/teams"
import { useDisplaySettings } from "@/hooks/useSettings"

interface LeaguePickerProps {
  selectedLeagues: string[]
  onSelectionChange: (leagues: string[]) => void
  /** Single select mode - only one league can be selected */
  singleSelect?: boolean
  maxHeight?: string
  showSearch?: boolean
  showSelectedBadges?: boolean
  maxBadges?: number
  /** Filter to show only leagues from a specific sport (e.g., "soccer") */
  sportFilter?: string
  /** Exclude leagues from a specific sport (e.g., "soccer" when using SoccerModeSelector) */
  excludeSport?: string
}

export function LeaguePicker({
  selectedLeagues,
  onSelectionChange,
  singleSelect = false,
  maxHeight = "max-h-64",
  showSearch = true,
  showSelectedBadges = true,
  maxBadges = 10,
  sportFilter,
  excludeSport,
}: LeaguePickerProps) {
  const [search, setSearch] = useState("")
  const [expandedSports, setExpandedSports] = useState<Set<string>>(new Set())
  const { data: leaguesResponse, isLoading } = useQuery({
    queryKey: ["cached-leagues"],
    queryFn: () => getLeagues(),
  })
  const cachedLeagues = leaguesResponse?.leagues

  // Fetch sport display names from database (single source of truth)
  const { data: sportsResponse } = useQuery({
    queryKey: ["sports"],
    queryFn: getSports,
    staleTime: 1000 * 60 * 60, // 1 hour - sports rarely change
  })
  const sportsMap = sportsResponse?.sports

  // Check if TSDB premium key is configured
  const { data: displaySettings } = useDisplaySettings()
  const hasPremiumKey = !!(displaySettings?.tsdb_api_key && displaySettings.tsdb_api_key.length > 3)

  // Convert to Set for easier operations
  const selectedSet = useMemo(() => new Set(selectedLeagues), [selectedLeagues])

  // Group leagues by sport (normalize to lowercase for consistent grouping)
  // When sportFilter is provided, only include leagues from that sport
  // When excludeSport is provided, exclude leagues from that sport
  const leaguesBySport = useMemo(() => {
    if (!cachedLeagues) return {}
    const grouped: Record<string, CachedLeague[]> = {}
    for (const league of cachedLeagues) {
      const sport = (league.sport || "other").toLowerCase()
      // Skip if sportFilter is set and doesn't match
      if (sportFilter && sport !== sportFilter.toLowerCase()) continue
      // Skip if excludeSport is set and matches
      if (excludeSport && sport === excludeSport.toLowerCase()) continue
      if (!grouped[sport]) grouped[sport] = []
      grouped[sport].push(league)
    }
    // Sort leagues within each sport (guard against null names from bad cache data)
    for (const sport of Object.keys(grouped)) {
      grouped[sport].sort((a, b) => (a.name || a.slug).localeCompare(b.name || b.slug))
    }
    return grouped
  }, [cachedLeagues, sportFilter, excludeSport])

  const sports = Object.keys(leaguesBySport).sort()

  // Check if any selected premium leagues lack a configured key
  const selectedPremiumWithoutKey = useMemo(() => {
    if (hasPremiumKey || !cachedLeagues) return false
    return selectedLeagues.some(slug => {
      const league = cachedLeagues.find(l => l.slug === slug)
      return league?.tsdb_tier === "premium"
    })
  }, [selectedLeagues, cachedLeagues, hasPremiumKey])

  // Select a league (single or multi mode)
  const selectLeague = (slug: string) => {
    if (singleSelect) {
      // Single select: replace current selection
      onSelectionChange([slug])
    } else {
      // Multi select: toggle
      const next = new Set(selectedSet)
      if (next.has(slug)) {
        next.delete(slug)
      } else {
        next.add(slug)
      }
      onSelectionChange(Array.from(next))
    }
  }

  // Global select/clear all (multi-select only)
  // When sportFilter is active, only operate on filtered leagues
  const selectAllLeagues = () => {
    const filteredSlugs = Object.values(leaguesBySport).flat().map(l => l.slug)
    // Merge with existing selections (don't lose other sports when filtering)
    const next = new Set(selectedSet)
    for (const slug of filteredSlugs) {
      next.add(slug)
    }
    onSelectionChange(Array.from(next))
  }

  const clearAllLeagues = () => {
    if (sportFilter || excludeSport) {
      // Only clear leagues that are in the filtered view
      const filteredSlugs = new Set(Object.values(leaguesBySport).flat().map(l => l.slug))
      const next = Array.from(selectedSet).filter(slug => !filteredSlugs.has(slug))
      onSelectionChange(next)
    } else {
      onSelectionChange([])
    }
  }

  // Per-sport select/clear (multi-select only)
  const selectAllInSport = (sport: string) => {
    const sportLeagues = leaguesBySport[sport] || []
    const next = new Set(selectedSet)
    for (const league of sportLeagues) {
      next.add(league.slug)
    }
    onSelectionChange(Array.from(next))
  }

  const clearAllInSport = (sport: string) => {
    const sportSlugs = new Set((leaguesBySport[sport] || []).map(l => l.slug))
    const next = new Set(selectedSet)
    for (const slug of sportSlugs) {
      next.delete(slug)
    }
    onSelectionChange(Array.from(next))
  }

  // Check if all leagues in a sport are selected
  const isSportFullySelected = (sport: string) => {
    const sportLeagues = leaguesBySport[sport] || []
    return sportLeagues.length > 0 && sportLeagues.every(l => selectedSet.has(l.slug))
  }

  // Toggle entire sport (multi-select only)
  const toggleSport = (sport: string) => {
    if (isSportFullySelected(sport)) {
      clearAllInSport(sport)
    } else {
      selectAllInSport(sport)
    }
  }

  // Toggle sport expand/collapse
  const toggleExpanded = (sport: string) => {
    setExpandedSports(prev => {
      const next = new Set(prev)
      if (next.has(sport)) {
        next.delete(sport)
      } else {
        next.add(sport)
      }
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Search */}
      {showSearch && (
        <Input
          placeholder="Search leagues..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}

      {/* Selected count and global actions (multi-select only) */}
      {!singleSelect && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {selectedSet.size} league{selectedSet.size !== 1 ? "s" : ""} selected
          </span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={selectAllLeagues}>
              Select All
            </Button>
            <Button variant="ghost" size="sm" onClick={clearAllLeagues} disabled={selectedSet.size === 0}>
              Clear All
            </Button>
          </div>
        </div>
      )}

      {/* Selected badges (multi-select only) */}
      {showSelectedBadges && selectedSet.size > 0 && !singleSelect && (
        <SelectedBadges
          items={Array.from(selectedSet).map((slug): BadgeItem => {
            const league = cachedLeagues?.find(l => l.slug === slug)
            return { key: slug, label: league ? getLeagueDisplayName(league, true) : slug, icon: league?.logo_url ?? undefined }
          })}
          maxBadges={maxBadges}
          onRemove={(slug) => selectLeague(slug)}
        />
      )}

      {/* Premium key warning */}
      {selectedPremiumWithoutKey && (
        <div className="text-xs text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded px-3 py-2">
          <Crown className="h-3 w-3 inline mr-1" />
          Premium leagues need a TSDB API key for full event coverage. Add one in Settings &gt; System.
        </div>
      )}

      {/* League picker by sport */}
      <div className={cn("overflow-y-auto border rounded-md divide-y", maxHeight)}>
        {sports
          .filter((sport) =>
            !search ||
            sport.toLowerCase().includes(search.toLowerCase()) ||
            leaguesBySport[sport].some(l =>
              l.slug.toLowerCase().includes(search.toLowerCase()) ||
              (l.name || "").toLowerCase().includes(search.toLowerCase()) ||
              (l.league_alias || "").toLowerCase().includes(search.toLowerCase())
            )
          )
          .map((sport) => {
            const leagues = leaguesBySport[sport]
            const filteredLeagues = search
              ? leagues.filter(l =>
                  l.slug.toLowerCase().includes(search.toLowerCase()) ||
                  (l.name || "").toLowerCase().includes(search.toLowerCase()) ||
                  (l.league_alias || "").toLowerCase().includes(search.toLowerCase())
                )
              : leagues

            // For search, if no individual leagues match but sport name matches, show all
            const displayLeagues = search && filteredLeagues.length === 0 &&
              sport.toLowerCase().includes(search.toLowerCase())
              ? leagues
              : filteredLeagues

            if (displayLeagues.length === 0) return null

            const allSelected = isSportFullySelected(sport)

            // Soccer in multi-select mode: show as single consolidated checkbox (too many leagues)
            // But NOT when sportFilter="soccer" or when searching - in those cases show individual leagues
            const hasSearchMatchInSoccer = search && filteredLeagues.length > 0 && sport.toLowerCase() === "soccer"
            if (!singleSelect && sport.toLowerCase() === "soccer" && !sportFilter && !hasSearchMatchInSoccer) {
              return (
                <label
                  key={sport}
                  className={cn(
                    "flex items-center gap-3 px-3 py-3 cursor-pointer hover:bg-accent",
                    allSelected && "bg-primary/10"
                  )}
                >
                  <Checkbox
                    checked={allSelected}
                    onCheckedChange={() => toggleSport(sport)}
                  />
                  <div className="flex-1">
                    <div className="font-medium text-sm">
                      {getSportDisplayName(sport, sportsMap)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      All {leagues.length} leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, etc.)
                    </div>
                  </div>
                </label>
              )
            }

            // Render leagues for this sport
            const isExpanded = expandedSports.has(sport) || !!search
            const selectedCount = displayLeagues.filter(l => selectedSet.has(l.slug)).length

            return (
              <div key={sport}>
                <div
                  className={cn(
                    "flex items-center justify-between px-3 py-2 bg-muted/50 cursor-pointer hover:bg-muted/70",
                    !sportFilter && "sticky top-0"
                  )}
                  onClick={() => toggleExpanded(sport)}
                >
                  <div className="flex items-center gap-2">
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="font-medium text-sm">
                      {getSportDisplayName(sport, sportsMap)} ({displayLeagues.length})
                    </span>
                    {selectedCount > 0 && !isExpanded && (
                      <Badge variant="secondary" className="text-xs h-5">
                        {selectedCount} selected
                      </Badge>
                    )}
                  </div>
                  {/* Select All button only in multi-select mode */}
                  {!singleSelect && isExpanded && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={(e) => {
                        e.stopPropagation()
                        allSelected ? clearAllInSport(sport) : selectAllInSport(sport)
                      }}
                    >
                      {allSelected ? "Clear" : "Select All"}
                    </Button>
                  )}
                </div>
                {isExpanded && (
                  <div className={cn(
                    "gap-1 p-2",
                    singleSelect ? "space-y-0.5" : "grid grid-cols-2 md:grid-cols-3"
                  )}>
                    {displayLeagues.map(league => {
                      const isSelected = selectedSet.has(league.slug)
                      return (
                        <label
                          key={league.slug}
                          className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded text-sm cursor-pointer hover:bg-accent",
                            isSelected && "bg-primary/10"
                          )}
                        >
                          {singleSelect ? (
                            // Single select: custom checkmark icon (no checkbox)
                            <button
                              type="button"
                              className="w-4 h-4 flex items-center justify-center"
                              onClick={() => selectLeague(league.slug)}
                            >
                              {isSelected && <Check className="h-4 w-4 text-primary" />}
                            </button>
                          ) : (
                            // Multi select: standard checkbox
                            <Checkbox
                              checked={isSelected}
                              onCheckedChange={() => selectLeague(league.slug)}
                            />
                          )}
                          {league.logo_url && (
                            <img src={league.logo_url} alt="" className="h-4 w-4 object-contain" />
                          )}
                          <span className="truncate">{getLeagueDisplayName(league, true)}</span>
                          {league.tsdb_tier === "premium" && (
                            <span title="Requires TSDB premium key">
                              <Crown className="h-3 w-3 text-amber-500 shrink-0" />
                            </span>
                          )}
                        </label>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
      </div>
    </div>
  )
}
