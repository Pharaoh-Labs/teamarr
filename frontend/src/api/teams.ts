import { api } from "./client"

export interface Team {
  id: number
  provider: string
  provider_team_id: string
  primary_league: string
  leagues: string[]
  sport: string
  team_name: string
  team_abbrev: string | null
  team_logo_url: string | null
  team_color: string | null
  channel_id: string
  channel_logo_url: string | null
  template_id: number | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface TeamCreate {
  provider?: string
  provider_team_id: string
  primary_league: string
  leagues?: string[]
  sport: string
  team_name: string
  team_abbrev?: string | null
  team_logo_url?: string | null
  team_color?: string | null
  channel_id: string
  channel_logo_url?: string | null
  template_id?: number | null
  active?: boolean
}

export interface TeamUpdate {
  team_name?: string | null
  team_abbrev?: string | null
  team_logo_url?: string | null
  team_color?: string | null
  channel_id?: string | null
  channel_logo_url?: string | null
  template_id?: number | null
  active?: boolean | null
  primary_league?: string | null
  leagues?: string[] | null
}

export interface TeamSearchResult {
  name: string
  abbrev: string | null
  short_name: string | null
  provider: string
  team_id: string
  league: string
  sport: string
  logo_url: string | null
}

export interface TeamSearchResponse {
  query: string
  count: number
  teams: TeamSearchResult[]
}

export async function listTeams(activeOnly = false): Promise<Team[]> {
  const params = activeOnly ? "?active_only=true" : ""
  return api.get(`/teams${params}`)
}

export async function createTeam(data: TeamCreate): Promise<Team> {
  return api.post("/teams", data)
}

export async function updateTeam(teamId: number, data: TeamUpdate): Promise<Team> {
  return api.put(`/teams/${teamId}`, data)
}

export async function deleteTeam(teamId: number): Promise<void> {
  return api.delete(`/teams/${teamId}`)
}

export async function searchTeams(
  query: string,
  league?: string,
  sport?: string
): Promise<TeamSearchResponse> {
  const params = new URLSearchParams({ q: query })
  if (league) params.set("league", league)
  if (sport) params.set("sport", sport)
  return api.get(`/cache/teams/search?${params}`)
}

// Cache API - Leagues
export interface CachedLeague {
  slug: string
  provider: string
  name: string
  sport: string
  team_count: number
  logo_url: string | null
  logo_url_dark: string | null
  import_enabled: boolean
  league_alias: string | null
}

export interface LeaguesResponse {
  count: number
  leagues: CachedLeague[]
}

export async function getLeagues(importOnly = false): Promise<LeaguesResponse> {
  const params = importOnly ? "?import_only=true" : ""
  return api.get(`/cache/leagues${params}`)
}

// Cache API - Teams for a league
export interface CachedTeam {
  id: number
  team_name: string
  team_abbrev: string | null
  team_short_name: string | null
  provider: string
  provider_team_id: string
  league: string
  sport: string
  logo_url: string | null
}

export async function getLeagueTeams(leagueSlug: string): Promise<CachedTeam[]> {
  return api.get(`/cache/leagues/${encodeURIComponent(leagueSlug)}/teams`)
}

// Sport display names
export interface SportsResponse {
  sports: Record<string, string>  // sport_code -> display_name
}

export async function getSports(): Promise<SportsResponse> {
  return api.get("/cache/sports")
}

// Team Picker Leagues - source of truth from team_cache
export interface TeamPickerLeague {
  slug: string
  sport: string
  sport_display_name: string
  provider: string
  team_count: number
  is_configured: boolean
  name: string
  logo_url: string | null
}

export interface TeamPickerLeaguesResponse {
  count: number
  leagues: TeamPickerLeague[]
}

export async function getTeamPickerLeagues(): Promise<TeamPickerLeaguesResponse> {
  return api.get("/cache/team-picker-leagues")
}
