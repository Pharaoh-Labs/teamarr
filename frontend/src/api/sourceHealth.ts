import { api } from "./client"

export interface SourceHealthRecommendation {
  group_id: number
  group_name: string
  kind: "quiet" | "low_coverage"
  reason: string
  leagues: string[]
  last_matched_at: string | null
  eligible_observations: number
  matched_observations: number
  sample_runs: number
  sample_days: number
  matching_types: { name?: boolean; team?: boolean; epg?: boolean }
  coverage: number | null
  decision: "keep" | "snooze" | null
}

export interface SourceHealthResponse {
  window_days: number
  recommendations: SourceHealthRecommendation[]
  hidden_count: number
}

export function getSourceHealth(includeHidden = false): Promise<SourceHealthResponse> {
  const query = includeHidden ? "?include_hidden=true" : ""
  return api.get(`/groups/health/recommendations${query}`)
}

export function keepSourceHealthRecommendation(groupId: number): Promise<{ group_id: number }> {
  return api.post(`/groups/${groupId}/health/keep`, {})
}

export function snoozeSourceHealthRecommendation(groupId: number): Promise<{ group_id: number }> {
  return api.post(`/groups/${groupId}/health/snooze`, {})
}

export function restoreSourceHealthRecommendation(
  groupId: number,
): Promise<{ group_id: number; restored: boolean }> {
  return api.delete(`/groups/${groupId}/health/decision`)
}
