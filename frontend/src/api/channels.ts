import { api } from "./client"

export interface ManagedChannel {
  id: number
  event_epg_group_id: number | null // Source group (provenance, not ownership)
  event_id: string
  event_provider: string
  tvg_id: string
  channel_name: string
  channel_number: string | null
  logo_url: string | null
  dispatcharr_channel_id: number | null
  dispatcharr_uuid: string | null
  home_team: string | null
  away_team: string | null
  event_date: string | null
  event_name: string | null
  league: string | null
  sport: string | null
  scheduled_delete_at: string | null
  sync_status: string
  created_at: string | null
  updated_at: string | null
  deleted_at: string | null
}

export interface ManagedChannelListResponse {
  channels: ManagedChannel[]
  total: number
}

export interface ReconciliationIssue {
  issue_type: string
  severity: string
  managed_channel_id: number | null
  dispatcharr_channel_id: number | null
  channel_name: string | null
  event_id: string | null
  details: Record<string, unknown>
  suggested_action: string | null
  auto_fixable: boolean
}

export interface ReconciliationSummary {
  orphan_teamarr: number
  orphan_dispatcharr: number
  duplicate: number
  drift: number
  total: number
  fixed: number
  skipped: number
  errors: number
}

export interface ReconciliationResponse {
  started_at: string | null
  completed_at: string | null
  summary: ReconciliationSummary
  issues_found: ReconciliationIssue[]
  issues_fixed: Record<string, unknown>[]
  issues_skipped: Record<string, unknown>[]
  errors: string[]
}

export interface SyncResponse {
  created_count: number
  existing_count: number
  skipped_count: number
  deleted_count: number
  error_count: number
  created: Record<string, unknown>[]
  errors: Record<string, unknown>[]
}

export interface DeleteResponse {
  success: boolean
  message: string
}

export interface PendingDeletionsResponse {
  count: number
  channels: Array<{
    id: number
    channel_name: string
    tvg_id: string
    scheduled_delete_at: string | null
    dispatcharr_channel_id: number | null
  }>
}

export async function listManagedChannels(
  groupId?: number,
  includeDeleted = false,
  sport?: string,
  league?: string,
): Promise<ManagedChannelListResponse> {
  const params = new URLSearchParams()
  if (groupId !== undefined) params.set("group_id", groupId.toString())
  if (sport) params.set("sport", sport)
  if (league) params.set("league", league)
  if (includeDeleted) params.set("include_deleted", "true")
  const query = params.toString()
  return api.get(`/channels/managed${query ? `?${query}` : ""}`)
}

export async function deleteManagedChannel(channelId: number): Promise<DeleteResponse> {
  return api.delete(`/channels/managed/${channelId}`)
}

export async function syncLifecycle(): Promise<SyncResponse> {
  return api.post("/channels/sync", {})
}

export async function getReconciliationStatus(): Promise<ReconciliationResponse> {
  return api.get("/channels/reconciliation/status")
}

export async function runReconciliation(
  autoFix: boolean,
): Promise<ReconciliationResponse> {
  return api.post("/channels/reconciliation/fix", {
    auto_fix: autoFix,
  })
}

export async function getPendingDeletions(): Promise<PendingDeletionsResponse> {
  return api.get("/channels/pending-deletions")
}

// Delete an orphan channel directly from Dispatcharr (not tracked in Teamarr)
export async function deleteDispatcharrChannel(channelId: number): Promise<DeleteResponse> {
  return api.delete(`/channels/dispatcharr/${channelId}`)
}

// Reset All - preview and delete all Teamarr channels from Dispatcharr
export interface ResetChannelInfo {
  dispatcharr_channel_id: number
  uuid: string | null
  tvg_id: string
  channel_name: string
  channel_number: string | null
  stream_count: number
}

export interface ResetPreviewResponse {
  success: boolean
  channel_count: number
  channels: ResetChannelInfo[]
}

export interface ResetExecuteResponse {
  success: boolean
  deleted_count: number
  error_count: number
  errors: string[]
}

export async function previewResetChannels(): Promise<ResetPreviewResponse> {
  return api.get("/channels/reset")
}

export async function executeResetChannels(): Promise<ResetExecuteResponse> {
  return api.post("/channels/reset", {})
}

export interface StreamRuleMatch {
  type: string
  value: string
  priority: number
  is_winner: boolean
}

export interface ChannelStreamEntry {
  dispatcharr_stream_id: number
  stream_name: string | null
  source_group: string | null
  m3u_account_name: string | null
  match_method: string | null
  match_type: string | null
  exception_keyword: string | null
  priority: number
  stream_stats: Record<string, unknown> | null
  stream_stats_updated_at: string | null
  matched_rules: StreamRuleMatch[]
  matched_event: string | null
  matched_league: string | null
  cache_match_method: string | null
  cache_created_at: string | null
  match_aliases: StreamNameMatch[]
  match_patterns: StreamNameMatch[]
  user_corrected: boolean
  corrected_at: string | null
}

export interface StreamNameMatch {
  text: string
  team: string
}

export interface ChannelStreamsResponse {
  streams: ChannelStreamEntry[]
  stats_refreshed: boolean
}

export async function getChannelStreams(channelId: number): Promise<ChannelStreamsResponse> {
  return api.get(`/channels/managed/${channelId}/streams`)
}
