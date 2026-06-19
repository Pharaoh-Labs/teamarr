/**
 * Custom Leagues API (epic teamarrv2-eqz).
 *
 * TSDB-only, premium-gated user-added leagues. The whole feature is locked
 * behind a TheSportsDB premium key — `getCustomLeagueCapability` reports the
 * gate state, and every write 403s server-side when it's off.
 */
import { api } from "./client"

export interface CustomLeague {
  league_code: string
  provider: string
  provider_league_id: string
  provider_league_name: string
  display_name: string
  sport: string
  event_type: string
  tsdb_tier: string | null
  enabled: number
  /** False = exists but the global subscription won't match its events (#240). */
  subscribed: boolean
}

export interface CustomLeagueCreate {
  league_code: string
  provider_league_id: string
  provider_league_name: string
  display_name: string
  sport: string
  event_type?: string | null
  tsdb_tier?: string | null
  allow_empty?: boolean
}

export type CustomLeagueUpdate = Omit<CustomLeagueCreate, "league_code" | "allow_empty">

export interface TeamRefreshResult {
  success: boolean
  league_code: string
  team_count: number
  error: string | null
}

/** Create returns the new league plus a scoped team-cache refresh summary (eqz.4). */
export type CustomLeagueCreateResult = CustomLeague & { team_refresh?: TeamRefreshResult }

export interface CustomLeagueCapability {
  enabled: boolean
  supported_sports: { sport_code: string; display_name: string }[]
}

export interface CustomLeagueSampleEvent {
  name: string | null
  home: string | null
  away: string | null
  date: string | null
  timestamp: string | null
}

export interface CustomLeagueTestResult {
  ok: boolean
  resolved_via: string
  provider_league_id: string
  tsdb_league_name: string | null
  name_matches: boolean | null
  tsdb_sport: string | null
  chosen_sport: string
  event_count: number
  sample_events: CustomLeagueSampleEvent[]
}

export interface CustomLeagueTestRequest {
  provider_league_id: string
  sport: string
  provider_league_name?: string | null
}

export async function getCustomLeagueCapability(): Promise<CustomLeagueCapability> {
  return api.get("/leagues/custom/capability")
}

export async function listCustomLeagues(): Promise<{ custom_leagues: CustomLeague[] }> {
  return api.get("/leagues/custom")
}

export async function testCustomLeague(
  data: CustomLeagueTestRequest
): Promise<CustomLeagueTestResult> {
  return api.post("/leagues/custom/test-fetch", data)
}

export async function createCustomLeague(
  data: CustomLeagueCreate
): Promise<CustomLeagueCreateResult> {
  return api.post("/leagues", data)
}

export async function updateCustomLeague(
  leagueCode: string,
  data: CustomLeagueUpdate
): Promise<CustomLeague> {
  return api.put(`/leagues/${encodeURIComponent(leagueCode)}`, data)
}

export async function deleteCustomLeague(leagueCode: string): Promise<void> {
  return api.delete(`/leagues/${encodeURIComponent(leagueCode)}`)
}
