import { api } from "./client"

export interface EPGGenerateRequest {
  team_ids?: number[] | null
  days_ahead?: number | null
}

export interface EPGGenerateResponse {
  programmes_count: number
  teams_processed: number
  events_processed: number
  duration_seconds: number
}

export interface StatsResponse {
  total_runs: number
  successful_runs: number
  failed_runs: number
  last_24h: {
    runs: number
    successful: number
    failed: number
    programmes_generated: number
    streams_matched: number
    channels_created: number
  }
  totals: {
    programmes_generated: number
    streams_matched: number
    streams_unmatched: number
    streams_cached: number
    channels_created: number
    channels_deleted: number
  }
  by_type: Record<string, number>
  avg_duration_ms: number
  last_run: string | null
  media_server_health?: MediaServerHealth[]
}

/** Per-server refresh health over recent runs (#649). */
export interface MediaServerHealth {
  kind: string
  server: string
  consecutive_failures: number
  last_error: string | null
  last_success_at: string | null
  failing: boolean
}

export interface ProcessingRun {
  id: number
  run_type: string
  run_id: string | null
  group_id: number | null
  team_id: number | null
  started_at: string
  completed_at: string | null
  duration_ms: number | null
  status: string
  error_message: string | null
  streams?: {
    fetched: number
    matched: number
    unmatched: number
    cached: number
  }
  channels?: {
    created: number
    updated: number
    deleted: number
    skipped: number
    errors: number
    active: number
  }
  programmes?: {
    total: number
    events: number
    pregame: number
    postgame: number
    idle: number
  }
  xmltv_size_bytes: number
  extra_metrics: Record<string, unknown>
}

export interface RunsResponse {
  runs: ProcessingRun[]
  count: number
}

export interface CacheStatus {
  last_refresh: string | null
  leagues_count: number
  teams_count: number
  refresh_duration_seconds: number
  is_stale: boolean
  is_empty: boolean
  refresh_in_progress: boolean
  last_error: string | null
}

export async function generateTeamEpg(request?: EPGGenerateRequest): Promise<EPGGenerateResponse> {
  return api.post("/epg/generate", request ?? {})
}

export function getTeamXmltvUrl(teamIds?: number[], daysAhead?: number): string {
  const params = new URLSearchParams()
  if (teamIds?.length) params.set("team_ids", teamIds.join(","))
  if (daysAhead) params.set("days_ahead", daysAhead.toString())
  const query = params.toString()
  return `/api/v1/epg/xmltv${query ? `?${query}` : ""}`
}

export async function getStats(): Promise<StatsResponse> {
  return api.get("/stats")
}

export async function getRecentRuns(
  limit = 20,
  runType?: string
): Promise<RunsResponse> {
  const params = new URLSearchParams({ limit: limit.toString() })
  if (runType) params.set("run_type", runType)
  return api.get(`/stats/runs?${params}`)
}

export async function getCacheStatus(): Promise<CacheStatus> {
  return api.get("/cache/status")
}

export async function refreshCache(): Promise<{ status: string; message: string }> {
  // The backend returns an SSE stream, we need to consume it and return the final result
  const response = await fetch("/api/v1/cache/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })

  if (!response.ok) {
    throw new Error(`Cache refresh failed: ${response.statusText}`)
  }

  // Read the SSE stream and extract the final status
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error("No response body")
  }

  const decoder = new TextDecoder()
  let lastStatus: { status: string; message: string } = { status: "unknown", message: "" }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const text = decoder.decode(value, { stream: true })
      // Parse SSE data lines: "data: {...}\n\n"
      const lines = text.split("\n")
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6))
            if (data.status === "complete") {
              // Backend sends "complete", not "completed"
              const teams = data.result?.teams_count || 0
              const leagues = data.result?.leagues_count || 0
              lastStatus = { status: "success", message: `Refreshed ${leagues} leagues, ${teams} teams` }
            } else if (data.status === "error") {
              lastStatus = { status: "error", message: data.message || "Refresh failed" }
            }
          } catch {
            // Ignore parse errors for heartbeats or malformed lines
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }

  if (lastStatus.status === "error") {
    throw new Error(lastStatus.message)
  }

  return lastStatus
}

// EPG Analysis types and functions

export interface EPGAnalysis {
  channels: {
    total: number
    team_based: number
    event_based: number
  }
  programmes: {
    total: number
    events: number
    pregame: number
    postgame: number
    idle: number
  }
  date_range: {
    start: string | null
    end: string | null
  }
  unreplaced_variables: string[]
  coverage_gaps: CoverageGap[]
}

export interface CoverageGap {
  channel: string
  after_program: string
  before_program: string
  after_stop: string
  before_start: string
  gap_minutes: number
}

export interface EPGContent {
  content: string
  total_lines: number
  truncated: boolean
  size_bytes: number
}

export async function getEPGAnalysis(): Promise<EPGAnalysis> {
  return api.get("/epg/analysis")
}

export async function getEPGContent(maxLines = 2000): Promise<EPGContent> {
  return api.get(`/epg/content?max_lines=${maxLines}`)
}

// Matched Streams types and functions

export interface MatchedStream {
  id: number
  run_id: number
  group_id: number
  group_name: string | null
  stream_id: number | null
  stream_name: string
  event_id: string
  event_name: string | null
  event_date: string | null
  home_team: string | null
  away_team: string | null
  league: string | null
  from_cache: boolean
  match_method: string | null
  confidence: number | null
  origin_match_method: string | null  // For cache hits: original method used
  created_at: string
}

export interface MatchedStreamsResponse {
  count: number
  run_id: number | null
  group_id: number | null
  streams: MatchedStream[]
}

export async function getMatchedStreams(
  runId?: number,
  groupId?: number,
  limit = 500
): Promise<MatchedStreamsResponse> {
  const params = new URLSearchParams()
  if (runId !== undefined) params.set("run_id", runId.toString())
  if (groupId !== undefined) params.set("group_id", groupId.toString())
  params.set("limit", limit.toString())
  return api.get(`/epg/matched-streams?${params}`)
}

// Failed Matches types and functions

export interface FailedMatch {
  id: number
  run_id: number
  group_id: number
  group_name: string | null
  stream_id: number | null
  stream_name: string
  reason: string
  exclusion_reason: string | null
  detail: string | null
  parsed_team1: string | null
  parsed_team2: string | null
  detected_league: string | null
  created_at: string
}

export interface FailedMatchesResponse {
  count: number
  run_id: number | null
  group_id: number | null
  reason_filter: string | null
  failures: FailedMatch[]
}

// Common type for streams that can be corrected (used by Event Matcher)
export interface CorrectableStream {
  group_id: number
  stream_id: number | null
  stream_name: string
  group_name: string | null
  league_hint: string | null  // detected_league for failed, league for matched
  current_event_id?: string | null  // Only for matched streams (to show what it's currently matched to)
}

export async function getFailedMatches(
  runId?: number,
  groupId?: number,
  reason?: string,
  limit = 500
): Promise<FailedMatchesResponse> {
  const params = new URLSearchParams()
  if (runId !== undefined) params.set("run_id", runId.toString())
  if (groupId !== undefined) params.set("group_id", groupId.toString())
  if (reason) params.set("reason", reason)
  params.set("limit", limit.toString())
  return api.get(`/epg/failed-matches?${params}`)
}

// Event search for manual match correction
export interface EventSearchResult {
  event_id: string
  event_name: string
  league: string
  league_name: string | null
  start_time: string
  home_team: string | null
  away_team: string | null
  status: string | null
}

export interface EventSearchResponse {
  count: number
  target_date: string
  events: EventSearchResult[]
}

export async function searchEvents(
  league?: string,
  team?: string,
  targetDate?: string,
  limit = 50
): Promise<EventSearchResponse> {
  const params = new URLSearchParams()
  if (league) params.set("league", league)
  if (team) params.set("team", team)
  if (targetDate) params.set("target_date", targetDate)
  params.set("limit", limit.toString())
  return api.get(`/epg/events/search?${params}`)
}

// Stream match correction
export interface MatchCorrectionRequest {
  group_id: number
  stream_id: number
  stream_name: string
  correct_event_id: string | null
  correct_league: string | null
  notes?: string | null
}

export interface MatchCorrectionResponse {
  success: boolean
  fingerprint: string
  message: string
  previous_event_id: string | null
  new_event_id: string | null
}

export async function correctStreamMatch(
  request: MatchCorrectionRequest
): Promise<MatchCorrectionResponse> {
  return api.post("/epg/streams/correct", request)
}

// Game Data Cache (schedules, scores, odds from providers)

export interface GameDataCacheStats {
  total_entries: number
  active_entries: number
  expired_entries: number
  hits: number
  misses: number
  hit_rate: number
  pending_writes: number
  pending_deletes: number
}

export interface GameDataCacheClearResponse {
  success: boolean
  entries_cleared: number
  message: string
}

export async function getGameDataCacheStats(): Promise<GameDataCacheStats> {
  return api.get("/game-data-cache/stats")
}

export async function clearGameDataCache(): Promise<GameDataCacheClearResponse> {
  return api.post("/game-data-cache/clear", {})
}

export async function cancelGeneration(): Promise<{ status: string; message: string }> {
  return api.post("/epg/generate/cancel", {})
}
