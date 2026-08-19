import type { CategoryType } from "@/api/detectionKeywords"

// Tab types - detection keyword categories plus team_aliases
export type TabType = CategoryType | "team_aliases"

// Detection Library sections: classification concerns plus matchup separators.
// Surfaced sections (in render order): team_aliases, event_type_keywords,
// league_hints, sport_hints, separators.
// Separators are global (detection_keywords category 'separators') and let users
// teach the classifier locale-specific matchup delimiters — e.g. " - " for
// "España - Inglaterra" — without us shipping risky defaults (a bare hyphen
// over-splits English titles). The remaining extraction categories
// (placeholders, card_segments, exclusions) aren't exposed as sections yet; they
// are managed via import/export or the API.

// Full mapping for type safety. Categories not surfaced as sections are not
// shown in the UI yet (import/export or API only).
export const TAB_NAMES: Record<TabType, string> = {
  team_aliases: "Team Aliases",
  event_type_keywords: "Event Type Detection",
  league_hints: "League Hints",
  sport_hints: "Sport Hints",
  separators: "Separators",
  // Not yet exposed as tabs (managed via import/export or API)
  placeholders: "Placeholders",
  card_segments: "Card Segments",
  exclusions: "Combat Exclusions",
}

/** Parse a sport hint target_value, which may be a JSON array or plain string. */
export function parseSportTarget(value: string | null): string[] {
  if (!value) return []
  if (value.startsWith("[")) {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.filter((s: unknown) => typeof s === "string")
    } catch {
      // fall through
    }
  }
  return [value]
}

/** Serialize sport targets for storage. Single value → plain string, multiple → JSON array. */
export function serializeSportTarget(sports: string[]): string {
  if (sports.length === 0) return ""
  if (sports.length === 1) return sports[0]
  return JSON.stringify(sports)
}

/**
 * Prepare a keyword for storage. Separators carry semantically meaningful
 * leading/trailing spaces (" - ", " vs ") that keep substring matching from
 * splitting mid-word, so they are preserved verbatim. Every other category is
 * trimmed to drop accidental whitespace.
 */
export function prepareKeyword(category: TabType, raw: string): string {
  return category === "separators" ? raw : raw.trim()
}

/** Download a JSON payload as a file. */
export function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
