/**
 * Pattern generator for the interactive selection feature.
 *
 * When a user selects text in a stream name and labels it (team1, date, etc.),
 * this module generates a regex pattern that captures that text across streams.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TextSelection {
  text: string
  field: "team1" | "team2" | "date" | "month" | "day" | "time" | "league"
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Escape special regex characters in a literal string. */
export function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// Latin letters including common accents (Western + Central European) so
// accented team names — Atlético, Bayern München, Plzeň, São Paulo — are
// captured, not just ASCII. Ranges: ASCII, Latin-1 letters (À-ÿ minus the ×/÷
// math symbols), and Latin Extended-A (Ā-ž) for Czech/Polish/etc.
const TEAM_CHARS = "A-Za-zÀ-ÖØ-öø-ÿĀ-ž"
const TEAM_BODY = `[${TEAM_CHARS}][${TEAM_CHARS} .'-]+[${TEAM_CHARS}.]`

/**
 * Attempt to generalize a literal selection into a broader pattern.
 *
 * For example, if the user selects "Arsenal" as team1, we want to match
 * any team name in that position — not just "Arsenal". This analyzes the
 * surrounding context to pick an appropriate capture pattern.
 */
function generalizeForField(
  field: TextSelection["field"],
  text: string,
  _streamName: string,
  _beforeText: string,
  _afterText: string
): string {
  switch (field) {
    case "team1":
    case "team2":
      // Team names: letters (accent-inclusive), spaces, dots, hyphens,
      // apostrophes (no digits — avoids grabbing dates)
      return `(${TEAM_BODY})`

    case "date":
      // Date: digits, slashes, dashes, spaces, month names
      if (/\d{4}-\d{2}-\d{2}/.test(text)) {
        return "(\\d{4}-\\d{2}-\\d{2})"
      }
      if (/\d{1,2}\/\d{1,2}/.test(text)) {
        return "(\\d{1,2}/\\d{1,2}(?:/\\d{2,4})?)"
      }
      // Generic date-like
      return "([\\d/\\-.]+)"

    case "month":
      // Month: name (Jan, January) or number (01, 1)
      if (/^[A-Za-z]+$/.test(text)) {
        return "([A-Za-z]+)"
      }
      return "(\\d{1,2})"

    case "day":
      // Day: 1-31 with optional ordinal suffix (1st, 2nd, 3rd)
      if (/\d{1,2}(?:st|nd|rd|th)/i.test(text)) {
        return "(\\d{1,2}(?:st|nd|rd|th)?)"
      }
      return "(\\d{1,2})"

    case "time":
      // Time: match what the user actually selected — don't add optional trailing groups
      // that could greedily consume nearby text (e.g., team names via case-insensitive [A-Z])
      if (/\d{1,2}:\d{2}:\d{2}\s*[A-Za-z]{2,4}$/.test(text)) {
        return "(\\d{1,2}:\\d{2}:\\d{2}\\s*[A-Z]{2,4})"
      }
      if (/\d{1,2}:\d{2}:\d{2}/.test(text)) {
        return "(\\d{1,2}:\\d{2}:\\d{2})"
      }
      if (/\d{1,2}:\d{2}\s*[AaPp][Mm]\s*[A-Za-z]{2,4}$/.test(text)) {
        return "(\\d{1,2}:\\d{2}\\s*[AaPp][Mm]\\s*[A-Z]{2,4})"
      }
      if (/\d{1,2}:\d{2}\s*[AaPp][Mm]/.test(text)) {
        return "(\\d{1,2}:\\d{2}\\s*[AaPp][Mm])"
      }
      return "(\\d{1,2}:\\d{2})"

    case "league":
      // League codes tend to be short uppercase or known names
      if (/^[A-Z]{2,6}$/.test(text)) {
        return "([A-Z]{2,6})"
      }
      // Multi-word league name — capture word characters and spaces
      return "([\\w][\\w ]+[\\w])"
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Generate a regex pattern from a user's text selection in a stream name.
 *
 * @param selection - What the user selected and labeled
 * @param streamName - The full stream name the selection came from
 * @returns A regex string with a JS-syntax named group ((?<name>...)), or null
 *   if generation fails. The form converts it to Python on save (PR #236).
 */
export function generatePattern(
  selection: TextSelection,
  streamName: string
): string | null {
  const { text, field } = selection
  if (!text || !streamName.includes(text)) return null

  const idx = streamName.indexOf(text)
  const before = streamName.slice(0, idx)
  const after = streamName.slice(idx + text.length)

  // Build an anchor from the immediate surrounding context
  const captureGroup = generalizeForField(field, text, streamName, before, after)
  const namedGroup = `(?<${field}>${captureGroup.slice(1, -1)})`

  // Find a stable anchor before the selection
  // Look for the nearest separator or keyword before the text
  let anchorBefore = ""
  const beforeTrimmed = before.trimEnd()
  if (beforeTrimmed.length > 0) {
    // Use the last few non-space characters as anchor (e.g., "vs.", ":", "|", "@")
    const separatorMatch = beforeTrimmed.match(
      /(?:vs\.?|v\.?|@|at|\||:|-|–|—)\s*$/i
    )
    if (separatorMatch) {
      anchorBefore = escapeRegex(separatorMatch[0])
    }
    // For date-related fields, also anchor on date separators (/, ., -)
    if (!anchorBefore && (field === "month" || field === "day" || field === "date")) {
      const dateSepMatch = before.match(/[/.\-]\s*$/)
      if (dateSepMatch) {
        anchorBefore = escapeRegex(dateSepMatch[0])
      }
    }
  }

  // Find a stable anchor after the selection
  let anchorAfter = ""
  const afterTrimmed = after.trimStart()
  if (afterTrimmed.length > 0) {
    const separatorMatch = afterTrimmed.match(
      /^\s*(?:vs\.?|v\.?|@|at|\||:|-|–|—|\()/i
    )
    if (separatorMatch) {
      anchorAfter = escapeRegex(separatorMatch[0])
    }
    // For date-related fields, also anchor on date separators
    if (!anchorAfter && (field === "month" || field === "day" || field === "date")) {
      const dateSepMatch = after.match(/^\s*[/.\-]/)
      if (dateSepMatch) {
        anchorAfter = escapeRegex(dateSepMatch[0])
      }
    }
  }

  // Assemble: anchor + whitespace + named capture + whitespace + anchor
  let pattern = ""
  if (anchorBefore) {
    pattern += anchorBefore + "\\s*"
  }
  pattern += namedGroup
  if (anchorAfter) {
    pattern += "\\s*" + anchorAfter
  }

  return pattern
}

/**
 * Build a combined teams regex from two separate selections.
 * Produces: (?<team1>...) separator (?<team2>...)
 */
export function generateTeamsPattern(
  team1Text: string,
  team2Text: string,
  streamName: string
): string | null {
  if (!team1Text || !team2Text) return null

  const idx1 = streamName.indexOf(team1Text)
  const idx2 = streamName.indexOf(team2Text)
  if (idx1 < 0 || idx2 < 0 || idx1 >= idx2) return null

  // Find what separates team1 and team2
  const between = streamName.slice(idx1 + team1Text.length, idx2)
  const sepMatch = between.match(/^\s*(vs\.?|v\.?|@|at|-|–|—)\s*$/i)
  let separator: string
  if (sepMatch) {
    separator = "\\s*" + escapeRegex(sepMatch[1]) + "\\s*"
  } else if (between.trim().length > 0) {
    // Non-standard separator (e.g., time between teams: "Fulham 15:00 Burnley")
    const trimmed = between.trim()
    if (/^\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?(?:\s*[A-Z]{2,4})?$/.test(trimmed)) {
      // Time-like separator — use a generic time pattern so it works across streams
      separator = "\\s+\\d{1,2}:\\d{2}(?::\\d{2})?(?:\\s*[AaPp][Mm])?\\s+"
    } else {
      separator = "\\s+" + escapeRegex(trimmed) + "\\s+"
    }
  } else {
    separator = "\\s+(?:vs\\.?|v\\.?|@|at)\\s+"
  }

  const team1Group = `(?<team1>${TEAM_BODY})`
  const team2Group = `(?<team2>${TEAM_BODY})`

  return team1Group + separator + team2Group
}
