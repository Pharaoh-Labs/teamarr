// API Response Types

// Team filter entry for include/exclude filtering
export interface TeamFilterEntry {
  provider: string      // e.g., "espn", "tsdb"
  team_id: string       // provider_team_id from team_cache
  league: string        // e.g., "nfl", "nba"
  name?: string | null  // For display only, not used in matching
}

// Soccer team to follow (for teams mode)
export interface SoccerFollowedTeam {
  provider: string      // e.g., "espn"
  team_id: string       // provider_team_id from team_cache
  name?: string | null  // For display only
}

export interface EventGroup {
  id: number
  name: string
  display_name: string | null  // Optional display name override for UI
  leagues: string[]
  soccer_mode: 'all' | 'teams' | 'manual' | null  // Soccer selection mode (null for non-soccer)
  soccer_followed_teams: SoccerFollowedTeam[] | null  // Teams to follow (for teams mode)
  stream_timezone: string | null  // IANA timezone for interpreting stream dates (e.g., 'America/New_York')
  channel_assignment_mode: string
  sort_order: number
  total_stream_count: number
  m3u_group_id: number | null
  m3u_group_name: string | null
  m3u_account_id: number | null
  m3u_account_name: string | null
  // Stream filtering
  stream_include_regex: string | null
  stream_include_regex_enabled: boolean
  stream_exclude_regex: string | null
  stream_exclude_regex_enabled: boolean
  custom_regex_teams: string | null
  custom_regex_teams_enabled: boolean
  custom_regex_date: string | null
  custom_regex_date_enabled: boolean
  custom_regex_month: string | null
  custom_regex_month_enabled: boolean
  custom_regex_day: string | null
  custom_regex_day_enabled: boolean
  custom_regex_time: string | null
  custom_regex_time_enabled: boolean
  custom_regex_league: string | null
  custom_regex_league_enabled: boolean
  // EVENT_CARD specific regex (UFC, Boxing, MMA)
  custom_regex_fighters: string | null
  custom_regex_fighters_enabled: boolean
  custom_regex_event_name: string | null
  custom_regex_event_name_enabled: boolean
  skip_builtin_filter: boolean
  name_match_enabled: boolean
  team_streams_enabled: boolean
  epg_match_enabled: boolean
  // Team filtering (canonical team selection, inherited by children)
  include_teams: TeamFilterEntry[] | null
  exclude_teams: TeamFilterEntry[] | null
  team_filter_mode: 'include' | 'exclude'
  bypass_filter_for_playoffs: boolean | null  // null = use default
  // Processing stats
  last_refresh: string | null
  stream_count: number
  matched_count: number  // Distinct streams matched (coverage)
  match_result_count: number  // Total matched results produced (volume; EPG fans out)
  // Filtering stats (pre-match)
  filtered_include_regex: number
  filtered_exclude_regex: number
  filtered_not_event: number
  filtered_team: number
  // Matching stats
  failed_count: number  // FAILED: Match attempted but couldn't find event
  streams_excluded: number  // EXCLUDED: Matched but excluded by timing (past/final/early)
  // Excluded breakdown by reason
  excluded_event_final: number
  excluded_event_past: number
  excluded_before_window: number
  excluded_league_not_included: number
  enabled: boolean
  // Per-group subscription overrides (null = inherit global)
  subscription_leagues: string[] | null
  subscription_soccer_mode: 'all' | 'teams' | 'manual' | null
  subscription_soccer_followed_teams: SoccerFollowedTeam[] | null
  created_at: string | null
  updated_at: string | null
  channel_count?: number | null
}

export interface EventGroupCreate {
  name: string
  display_name?: string | null  // Optional display name override
  leagues: string[]
  soccer_mode?: 'all' | 'teams' | 'manual' | null  // Soccer selection mode (null for non-soccer)
  soccer_followed_teams?: SoccerFollowedTeam[] | null  // Teams to follow (for teams mode)
  stream_timezone?: string | null  // IANA timezone for interpreting stream dates
  channel_assignment_mode?: string
  sort_order?: number
  total_stream_count?: number
  m3u_group_id?: number | null
  m3u_group_name?: string | null
  m3u_account_id?: number | null
  m3u_account_name?: string | null
  // Stream filtering
  stream_include_regex?: string | null
  stream_include_regex_enabled?: boolean
  stream_exclude_regex?: string | null
  stream_exclude_regex_enabled?: boolean
  custom_regex_teams?: string | null
  custom_regex_teams_enabled?: boolean
  custom_regex_date?: string | null
  custom_regex_date_enabled?: boolean
  custom_regex_month?: string | null
  custom_regex_month_enabled?: boolean
  custom_regex_day?: string | null
  custom_regex_day_enabled?: boolean
  custom_regex_time?: string | null
  custom_regex_time_enabled?: boolean
  custom_regex_league?: string | null
  custom_regex_league_enabled?: boolean
  // EVENT_CARD specific regex (UFC, Boxing, MMA)
  custom_regex_fighters?: string | null
  custom_regex_fighters_enabled?: boolean
  custom_regex_event_name?: string | null
  custom_regex_event_name_enabled?: boolean
  skip_builtin_filter?: boolean
  name_match_enabled?: boolean
  team_streams_enabled?: boolean
  epg_match_enabled?: boolean
  // Team filtering (canonical team selection, inherited by children)
  include_teams?: TeamFilterEntry[] | null
  exclude_teams?: TeamFilterEntry[] | null
  team_filter_mode?: 'include' | 'exclude'
  bypass_filter_for_playoffs?: boolean | null  // null = use default
  enabled?: boolean
  // Per-group subscription overrides (null = inherit global)
  subscription_leagues?: string[] | null
  subscription_soccer_mode?: 'all' | 'teams' | 'manual' | null
  subscription_soccer_followed_teams?: SoccerFollowedTeam[] | null
}

export interface EventGroupUpdate extends Partial<EventGroupCreate> {
  clear_display_name?: boolean
  clear_stream_timezone?: boolean
  clear_m3u_group_id?: boolean
  clear_m3u_group_name?: boolean
  clear_m3u_account_id?: boolean
  clear_m3u_account_name?: boolean
  clear_stream_include_regex?: boolean
  clear_stream_exclude_regex?: boolean
  clear_custom_regex_teams?: boolean
  clear_custom_regex_date?: boolean
  clear_custom_regex_month?: boolean
  clear_custom_regex_day?: boolean
  clear_custom_regex_time?: boolean
  clear_custom_regex_league?: boolean
  clear_custom_regex_fighters?: boolean
  clear_custom_regex_event_name?: boolean
  clear_include_teams?: boolean
  clear_exclude_teams?: boolean
  clear_soccer_mode?: boolean
  clear_soccer_followed_teams?: boolean
  clear_subscription_leagues?: boolean
  clear_subscription_soccer_mode?: boolean
  clear_subscription_soccer_followed_teams?: boolean
}

export interface EventGroupListResponse {
  groups: EventGroup[]
  total: number
}

export interface BulkGroupUpdateRequest {
  group_ids: number[]
  leagues?: string[]
  stream_timezone?: string | null  // IANA timezone for interpreting stream dates
  clear_stream_timezone?: boolean
  name_match_enabled?: boolean | null
  team_streams_enabled?: boolean | null
  epg_match_enabled?: boolean | null
  // Team filtering
  include_teams?: TeamFilterEntry[] | null
  exclude_teams?: TeamFilterEntry[] | null
  team_filter_mode?: 'include' | 'exclude'
  bypass_filter_for_playoffs?: boolean | null
  clear_include_teams?: boolean
  clear_exclude_teams?: boolean
  clear_bypass_filter_for_playoffs?: boolean
  // Per-group subscription overrides
  subscription_leagues?: string[] | null
  subscription_soccer_mode?: 'all' | 'teams' | 'manual' | null
  subscription_soccer_followed_teams?: SoccerFollowedTeam[] | null
  clear_subscription_leagues?: boolean
  clear_subscription_soccer_mode?: boolean
  clear_subscription_soccer_followed_teams?: boolean
}

export interface BulkGroupUpdateResult {
  group_id: number
  name: string
  success: boolean
  error?: string
}

export interface BulkGroupUpdateResponse {
  results: BulkGroupUpdateResult[]
  total_requested: number
  total_updated: number
  total_failed: number
}

export interface Template {
  id: number
  name: string
  title_template: string
  description_template: string | null
  pregame_title_template: string | null
  pregame_description_template: string | null
  postgame_title_template: string | null
  postgame_description_template: string | null
  pregame_duration_minutes: number
  postgame_duration_minutes: number
  created_at: string | null
  updated_at: string | null
}

export interface TemplateListResponse {
  templates: Template[]
  total: number
}

export interface Team {
  id: number
  team_id: string
  provider: string
  name: string
  display_name: string
  abbreviation: string | null
  league: string
  sport: string | null
  template_id: number | null
  channel_number: string | null
  channel_group_id: number | null
  channel_profile_ids: number[] | null  // null = use global default
  active: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TeamListResponse {
  teams: Team[]
  total: number
}

export interface ManagedChannel {
  id: number
  event_epg_group_id: number | null
  team_id: number | null
  channel_id: string | null
  channel_number: string | null
  channel_name: string
  event_id: string | null
  event_name: string | null
  start_time: string | null
  end_time: string | null
  sync_status: string
  created_at: string | null
  updated_at: string | null
  deleted_at: string | null
}

export interface ChannelListResponse {
  channels: ManagedChannel[]
  total: number
}

export interface Settings {
  dispatcharr_url: string | null
  dispatcharr_api_key: string | null
  channel_range_start: number
  channel_range_end: number | null
  scheduler_enabled: boolean
  scheduler_interval_minutes: number
}

export interface CacheStatus {
  leagues_cached: number
  teams_cached: number
  last_refresh: string | null
}

export interface HealthResponse {
  status: string
  version?: string
}

// Preview (stream matching without channel creation)
export interface PreviewStream {
  stream_id: number
  stream_name: string
  matched: boolean
  event_id: string | null
  event_name: string | null
  home_team: string | null
  away_team: string | null
  league: string | null
  start_time: string | null
  from_cache: boolean
  exclusion_reason: string | null
}

export interface PreviewGroupResponse {
  group_id: number
  group_name: string
  total_streams: number
  filtered_count: number
  matched_count: number
  unmatched_count: number
  filtered_not_event: number
  filtered_include_regex: number
  filtered_exclude_regex: number
  cache_hits: number
  cache_misses: number
  streams: PreviewStream[]
  errors: string[]
}

// Team Aliases
export interface TeamAlias {
  id: number
  alias: string
  league: string
  provider: string
  team_id: string
  team_name: string
  created_at: string | null
}

export interface TeamAliasCreate {
  alias: string
  league: string
  team_id: string
  team_name: string
  provider?: string
}

export interface TeamAliasListResponse {
  aliases: TeamAlias[]
  total: number
}
