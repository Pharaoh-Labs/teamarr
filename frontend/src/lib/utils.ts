import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Sport emoji mapping for UI display.
 */
export const SPORT_EMOJIS: Record<string, string> = {
  football: "🏈",
  basketball: "🏀",
  baseball: "⚾",
  hockey: "🏒",
  soccer: "⚽",
  mma: "🥊",
  boxing: "🥊",
  golf: "⛳",
  tennis: "🎾",
  lacrosse: "🥍",
  cricket: "🏏",
  rugby: "🏉",
  volleyball: "🏐",
  softball: "🥎",
  racing: "🏎️",
  wrestling: "🤼",
  "australian-football": "🏉",
  default: "🏆",
}

/**
 * Get emoji for a sport.
 */
export function getSportEmoji(sport: string): string {
  return SPORT_EMOJIS[sport.toLowerCase()] ?? SPORT_EMOJIS.default
}

/**
 * Get display name for a sport.
 * Uses provided sportsMap from API when available, otherwise falls back to title case.
 *
 * @param sport - Sport code (e.g., "football", "australian-football")
 * @param sportsMap - Optional map of sport_code -> display_name from /cache/sports API
 * @returns Display name (e.g., "Football", "Australian Football")
 */
export function getSportDisplayName(
  sport: string,
  sportsMap?: Record<string, string>
): string {
  if (!sport) return ""
  const lower = sport.toLowerCase()

  // Use API data if available
  if (sportsMap?.[lower]) {
    return sportsMap[lower]
  }

  // Fallback: title case with hyphen/underscore handling
  return sport
    .split(/[-_]/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ")
}

/**
 * Get display name for a league.
 * @param league - League object with name and optional league_alias
 * @param short - If true, prefer league_alias for short display (e.g., "EPL" instead of "English Premier League")
 * @returns Display name string
 */
export function getLeagueDisplayName(
  league: { name: string; slug?: string; league_alias?: string | null },
  short = false
): string {
  if (short && league.league_alias) {
    return league.league_alias
  }
  return league.name || league.slug || "Unknown"
}

/**
 * Human label for a failure taxonomy code (#661/#662) as stored on
 * `epg_failed_matches.reason`: a FailedReason value, or a `filtered:` /
 * `skipped:` prefixed verdict. Shared by the run-history Failed drill-down and
 * the source preview modal so one stream reads the same in both.
 */
export function getFailedReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    teams_not_parsed: "Could not parse teams",
    team1_not_found: "Team 1 not found",
    team2_not_found: "Team 2 not found",
    both_teams_not_found: "Neither team found",
    no_common_league: "No common league",
    fixture_not_in_league: "Teams don't play in this league",
    no_league_detected: "No league detected",
    ambiguous_league: "Ambiguous league",
    no_event_found: "No event found",
    no_event_card_match: "No event card match",
    no_racing_match: "No racing match",
    no_tennis_match: "No tennis match",
    tennis_tournament_mismatch: "Different tournament",
    tennis_matchup_unknown: "Tennis matchup not known",
    no_epg_program_match: "No guide programme matched",
    date_mismatch: "Date mismatch",
    candidates_gated: "No candidate in window",
    unmatched: "Unmatched",
    "filtered:not_event": "Not an event",
    "filtered:league_not_included": "League not enabled",
    "filtered:include_regex": "Excluded by include pattern",
    "filtered:exclude_regex": "Excluded by exclude pattern",
    "filtered:stale": "Stale stream",
    "skipped:unclassifiable": "Linear channel (no matchup)",
    "skipped:name_match_disabled": "Stream Name matching off",
    "skipped:team_streams_disabled": "Team matching off",
  }
  return labels[reason] || reason
}
