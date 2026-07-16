import { api } from "./client"
import type {
  BulkGroupUpdateRequest,
  BulkGroupUpdateResponse,
  EventGroup,
  EventGroupCreate,
  EventGroupListResponse,
  EventGroupUpdate,
  PreviewGroupResponse,
} from "./types"

export async function listGroups(
  includeDisabled = false,
  includeStats = true
): Promise<EventGroupListResponse> {
  const params = new URLSearchParams()
  if (includeDisabled) params.set("include_disabled", "true")
  if (includeStats) params.set("include_stats", "true")
  return api.get(`/groups?${params}`)
}

export async function getGroup(groupId: number): Promise<EventGroup> {
  return api.get(`/groups/${groupId}`)
}

/** A group whose Dispatcharr M3U source channel-group no longer exists (lylt). */
export interface StaleGroup {
  id: number
  name: string
  display_name: string | null
  m3u_group_id: number | null
  m3u_group_name: string | null
  m3u_account_id: number | null
  m3u_account_name: string | null
  source_last_seen: string | null
  total_stream_count: number
}

export async function getStaleGroups(): Promise<StaleGroup[]> {
  return api.get("/groups/stale")
}

/** Re-bind suggestion for a stale source — a likely-renamed live group (#450). */
export interface StaleRebindSuggestion {
  group_id: number
  group_name: string
  old_group_name: string
  candidate_group_id: number
  candidate_group_name: string
  similarity: number
  suggested_pattern: string | null
}

export async function getStaleRebindSuggestions(): Promise<StaleRebindSuggestion[]> {
  return api.get("/groups/stale/suggestions")
}

export interface GroupRebindRequest {
  m3u_group_id: number
  m3u_group_name: string
  /** Adopt this name pattern in the same click (rename-proofing). */
  pattern?: string | null
}

export async function rebindGroup(
  groupId: number,
  data: GroupRebindRequest
): Promise<{ id: number }> {
  return api.post(`/groups/${groupId}/rebind`, data)
}

export async function createGroup(data: EventGroupCreate): Promise<EventGroup> {
  return api.post("/groups", data)
}

/** Live resolution of a group-name pattern against Dispatcharr M3U groups (#450). */
export interface GroupPatternPreview {
  valid: boolean
  total: number
  matches: { id: number; name: string }[]
}

export async function previewGroupPattern(
  pattern: string
): Promise<GroupPatternPreview> {
  return api.post("/groups/dispatcharr/group-pattern-preview", { pattern })
}

export async function updateGroup(
  groupId: number,
  data: EventGroupUpdate
): Promise<EventGroup> {
  return api.put(`/groups/${groupId}`, data)
}

export async function deleteGroup(
  groupId: number
): Promise<{ success: boolean; message: string; channels_deleted: number }> {
  return api.delete(`/groups/${groupId}`)
}

export async function enableGroup(
  groupId: number
): Promise<{ success: boolean; message: string }> {
  return api.post(`/groups/${groupId}/enable`)
}

export async function disableGroup(
  groupId: number
): Promise<{ success: boolean; message: string }> {
  return api.post(`/groups/${groupId}/disable`)
}

export async function previewGroup(
  groupId: number
): Promise<PreviewGroupResponse> {
  return api.get(`/groups/${groupId}/preview`)
}

export interface RawStream {
  stream_id: number
  stream_name: string
  /** Reason stream would be filtered by builtin filters (null if passes) */
  builtin_filtered: string | null
}

export interface RawStreamsResponse {
  group_id: number
  group_name: string
  total: number
  streams: RawStream[]
}

export async function getRawStreams(
  groupId: number
): Promise<RawStreamsResponse> {
  return api.get(`/groups/${groupId}/streams/raw`)
}

// Pipeline-truth extraction tester (#458) — runs the REAL Python extraction
// functions server-side; the client-side JS highlighting is only approximate.

export interface ExtractionPatterns {
  teams_pattern?: string | null
  teams_enabled?: boolean
  date_pattern?: string | null
  date_enabled?: boolean
  month_pattern?: string | null
  month_enabled?: boolean
  day_pattern?: string | null
  day_enabled?: boolean
  time_pattern?: string | null
  time_enabled?: boolean
  league_pattern?: string | null
  league_enabled?: boolean
  fighters_pattern?: string | null
  fighters_enabled?: boolean
  event_name_pattern?: string | null
  event_name_enabled?: boolean
}

export interface ExtractionFieldResult {
  matched: boolean
  values: string[]
}

export interface StreamExtractionResult {
  stream_name: string
  teams: ExtractionFieldResult | null
  fighters: ExtractionFieldResult | null
  event_name: ExtractionFieldResult | null
  date: ExtractionFieldResult | null
  time: ExtractionFieldResult | null
  league: ExtractionFieldResult | null
}

export interface TestExtractionResponse {
  results: StreamExtractionResult[]
  pattern_errors: Record<string, string>
  warnings: string[]
}

export async function testExtraction(
  streamNames: string[],
  patterns: ExtractionPatterns
): Promise<TestExtractionResponse> {
  return api.post("/groups/test-extraction", {
    stream_names: streamNames,
    patterns,
  })
}

export async function bulkUpdateGroups(
  data: BulkGroupUpdateRequest
): Promise<BulkGroupUpdateResponse> {
  return api.put("/groups/bulk", data)
}

export interface ClearCacheResponse {
  success: boolean
  group_id?: number
  group_name?: string
  entries_cleared?: number
  total_cleared?: number
  by_group?: { group_id: number; cleared: number }[]
}

export async function clearGroupMatchCache(
  groupId: number
): Promise<ClearCacheResponse> {
  return api.post(`/groups/${groupId}/cache/clear`)
}

export async function clearGroupsMatchCache(
  groupIds: number[]
): Promise<ClearCacheResponse> {
  return api.post("/groups/cache/clear", { group_ids: groupIds })
}

export async function clearAllMatchCache(): Promise<ClearCacheResponse> {
  return api.post("/groups/cache/clear-all")
}

export interface MatchCacheStats {
  total_entries: number
}

export async function getMatchCacheStats(): Promise<MatchCacheStats> {
  return api.get("/groups/cache/stats")
}

export async function reorderGroups(
  groups: { group_id: number; sort_order: number }[]
): Promise<{ success: boolean; updated_count: number; message: string }> {
  return api.post("/groups/reorder", { groups })
}

