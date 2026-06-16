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
 * Get unique sports from leagues, normalized and sorted alphabetically.
 * @param sportsMap - Optional map from /cache/sports API for accurate display names
 */
export function getUniqueSports(
  leagues: { sport: string | null }[],
  sportsMap?: Record<string, string>
): string[] {
  const sportSet = new Set<string>()
  for (const league of leagues) {
    if (league.sport) {
      sportSet.add(getSportDisplayName(league.sport, sportsMap))
    }
  }
  return [...sportSet].sort()
}

/**
 * Sort leagues: import_enabled first (alphabetically), then rest (alphabetically).
 */
export function sortLeaguesImportFirst<T extends { name: string; import_enabled?: boolean }>(
  leagues: T[]
): T[] {
  return [...leagues].sort((a, b) => {
    const aEnabled = a.import_enabled ?? false
    const bEnabled = b.import_enabled ?? false

    if (aEnabled !== bEnabled) {
      return bEnabled ? 1 : -1
    }

    return (a.name ?? "").localeCompare(b.name ?? "")
  })
}

/**
 * Filter leagues by sport (case-insensitive) and sort with import_enabled first.
 * @param sportsMap - Optional map from /cache/sports API for accurate display names
 */
export function filterLeaguesBySport<T extends { sport: string | null; name: string; import_enabled?: boolean }>(
  leagues: T[],
  sport: string,
  sportsMap?: Record<string, string>
): T[] {
  const normalizedSport = getSportDisplayName(sport, sportsMap)
  const filtered = leagues.filter(
    (l) => l.sport && getSportDisplayName(l.sport, sportsMap) === normalizedSport
  )
  return sortLeaguesImportFirst(filtered)
}
