import { api } from "./client"

// Why a candidate is suggested: it matched games, or only its name fits.
export type SuggestionTier = "games" | "name_only"

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
  best_game_matches: number
  days_matched: number
  scans: number
  last_seen_at: string | null
  last_matched_at: string | null
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
