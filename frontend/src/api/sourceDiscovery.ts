import { api } from "./client"

// Why a candidate is suggested: its streams matched events, they matched teams
// of the league its name names, or only its name fits.
export type SuggestionTier = "games" | "teams" | "name_only"

export interface SourceCandidate {
  id: number
  m3u_group_id: number
  m3u_group_name: string
  m3u_account_ids: number[]
  stream_count: number
  status: "new" | "accepted" | "dismissed"
  tier: SuggestionTier | null
  name_leagues: string[]
  leagues: Record<string, number>
  team_leagues: Record<string, number>
  events: number
  best_game_matches: number
  days_matched: number
  evidence_days: number
  // Why automatic mode has not added this group; null = it will on the next scan.
  // Absent meaning when no league is set to automatic (always null then).
  auto_hold: string | null
  scans: number
  last_seen_at: string | null
  last_matched_at: string | null
  // M3U account the group comes from; the list is organized by it.
  m3u_account_name: string | null
  // A stronger suggestion carrying the same events, if any (information only).
  same_events_as: string | null
}

export interface DiscoveryScanState {
  running: boolean
  progress: { done: number; total: number; group: string } | null
  last:
    | ({ finished_at: string; error?: string } & Partial<{
        groups_scanned: number
        groups_with_games: number
        duration_seconds: number
        sources_disabled: number
        sources_reenabled: number
        sources_removed: number
        sources_auto_added: number
      }>)
    | null
}

export interface SourceCandidateList {
  window_days: number
  candidates: SourceCandidate[]
  scan: DiscoveryScanState
}

export async function getSourceCandidates(includeDismissed = false): Promise<SourceCandidateList> {
  const qs = includeDismissed ? "?include_dismissed=true" : ""
  return api.get(`/source-discovery/candidates${qs}`)
}

export async function startDiscoveryScan(): Promise<{ started: boolean }> {
  return api.post("/source-discovery/scan", {})
}

export async function acceptSourceCandidate(id: number): Promise<{ source_group_id: number }> {
  return api.post(`/source-discovery/candidates/${id}/accept`, {})
}

export async function dismissSourceCandidate(id: number): Promise<{ status: string }> {
  return api.post(`/source-discovery/candidates/${id}/dismiss`, {})
}

export async function restoreSourceCandidate(id: number): Promise<{ status: string }> {
  return api.post(`/source-discovery/candidates/${id}/restore`, {})
}
