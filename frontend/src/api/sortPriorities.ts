import { api } from "./client"
import type { TeamFilterEntry } from "./types"

// Sort Priority Types
export interface SortPriority {
  id: number
  sport: string
  league_code: string | null
  sort_priority: number
  display_name?: string | null
  channel_count?: number | null
}

export interface SortPriorityCreate {
  sport: string
  league_code?: string | null
  sort_priority: number
}

export interface SortPriorityReorderItem {
  sport: string
  league_code?: string | null
  priority: number
}

export interface AutoPopulateResponse {
  added: number
  message: string
}

// API Functions
export async function getSortPriorities(): Promise<SortPriority[]> {
  return api.get("/sort-priorities")
}

export async function getActiveSortPriorities(): Promise<SortPriority[]> {
  return api.get("/sort-priorities/active")
}

export async function createSortPriority(
  data: SortPriorityCreate
): Promise<SortPriority> {
  return api.post("/sort-priorities", data)
}

export async function deleteSortPrioritySport(sport: string): Promise<void> {
  return api.delete(`/sort-priorities/${sport}`)
}

export async function deleteSortPriorityLeague(
  sport: string,
  leagueCode: string
): Promise<void> {
  return api.delete(`/sort-priorities/${sport}/${leagueCode}`)
}

export async function reorderSortPriorities(
  orderedList: SortPriorityReorderItem[]
): Promise<{ success: boolean; updated: number }> {
  return api.put("/sort-priorities/reorder", { ordered_list: orderedList })
}

export async function autoPopulateSortPriorities(): Promise<AutoPopulateResponse> {
  return api.post("/sort-priorities/auto-populate", {})
}

// Priority Teams — a team-level tier that floats channels above sport/league order
export interface PriorityTeam {
  id: number
  provider: string
  provider_team_id: string
  team_name: string
  league: string | null
  sport: string
}

export async function getPriorityTeams(): Promise<PriorityTeam[]> {
  return api.get("/sort-priorities/teams")
}

export async function addPriorityTeam(team: TeamFilterEntry): Promise<PriorityTeam> {
  return api.post("/sort-priorities/teams", {
    provider: team.provider,
    team_id: team.team_id,
    league: team.league,
  })
}

export async function deletePriorityTeam(id: number): Promise<void> {
  return api.delete(`/sort-priorities/teams/${id}`)
}
