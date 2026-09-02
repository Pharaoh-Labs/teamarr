import type { LucideIcon } from "lucide-react"
import { ClipboardList, Pencil, Target, Calendar, Settings, Link2 } from "lucide-react"
import type {
  TemplateCreate,
  FillerContent,
  ConditionalDescription,
  ConditionalSettings,
} from "@/api/templates"
import type { Tab } from "./types"

export const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "basic", label: "Basics", icon: ClipboardList },
  { id: "defaults", label: "Defaults", icon: Pencil },
  { id: "conditions", label: "Conditions", icon: Target },
  { id: "fillers", label: "Fillers", icon: Calendar },
  { id: "xmltv", label: "EPG Options", icon: Settings },
]

// Edit-mode only (#461): a new template has no id to look up assignments for,
// and the guided create stepper (which walks TABS) shouldn't end on it.
export const ASSIGNMENTS_TAB: { id: Tab; label: string; icon: LucideIcon } = {
  id: "assignments",
  label: "Assignments",
  icon: Link2,
}

// Default filler content
export const DEFAULT_PREGAME: FillerContent = {
  title: "Coming up: {league} {sport} starting at {game_time.next}",
  subtitle: "{team1} {at_vs} {team2}",
  description: "The {away_team_record.next} {away_team.next} travel to {venue_city} to play the {home_team_record.next} {home_team.next} today at {game_time.next}.",
  art_url: null,
}

export const DEFAULT_POSTGAME: FillerContent = {
  title: "{league} {sport}: {team_name} Postgame Recap",
  subtitle: "{team1.last} {at_vs.last} {team2.last}",
  description: "{team_name} {result_text.last} the {opponent.last} {final_score.last}",
  art_url: null,
}

export const DEFAULT_IDLE: FillerContent = {
  title: "No {team_name} Game Today",
  subtitle: "Next game: {game_date.next} at {game_time.next} {vs_at.next} the {opponent.next}",
  description: "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
  art_url: null,
}

// Recap-first postgame condition-row seed (#420, cajd.6): has_recap fires
// only when the provider published a recap. Team fillers read the LAST game
// via the .last suffix; event fillers read the channel's event directly.
export function seedPostgameRows(isTeamTemplate: boolean): ConditionalDescription[] {
  return [
    {
      condition: "has_recap",
      template: isTeamTemplate ? "{game_recap.last}" : "{game_recap}",
      priority: 10,
      label: "Recap (provider)",
    },
  ]
}

// Frontend twin of the backend's legacy_conditional_to_rows (#420): an
// ENABLED legacy final/not-final conditional becomes up to two disjoint
// is_final/is_not_final rows. Used when loading a template whose rows column
// is still empty, so the editor shows the rows generation actually uses;
// saving then persists the rows and the neutralized legacy dict.
export function legacyConditionalToRows(
  cond: ConditionalSettings | null | undefined,
): ConditionalDescription[] {
  if (!cond?.enabled) return []
  const rows: ConditionalDescription[] = []
  const push = (
    condition: string,
    title: string | null,
    subtitle: string | null,
    description: string | null,
    label: string,
  ) => {
    if (!title && !subtitle && !description) return
    rows.push({
      condition,
      priority: 50,
      label,
      template: description || "",
      ...(title ? { title } : {}),
      ...(subtitle ? { subtitle } : {}),
    })
  }
  push("is_final", cond.title_final, cond.subtitle_final, cond.description_final, "Final (legacy)")
  push(
    "is_not_final",
    cond.title_not_final,
    cond.subtitle_not_final,
    cond.description_not_final,
    "In progress (legacy)",
  )
  return rows
}

/** True when rows are still exactly a seedPostgameRows() output (either flavor). */
export function isUntouchedPostgameSeed(rows: ConditionalDescription[] | null | undefined): boolean {
  if (!rows || rows.length !== 1) return false
  const [row] = rows
  return (
    row.condition === "has_recap" &&
    row.priority === 10 &&
    (row.template === "{game_recap.last}" || row.template === "{game_recap}") &&
    !row.title &&
    !row.subtitle
  )
}

export const DEFAULT_FORM: TemplateCreate = {
  name: "",
  // Event templates are the primary focus, so new templates default to "event"
  // (pre-selected in the create type chooser).
  template_type: "event",
  title_format: "{league} {sport}",
  subtitle_template: "{team1} {at_vs} {team2}",
  description_template: "{matchup} | {venue_full}",
  program_art_url: null,
  game_duration_mode: "sport",
  game_duration_override: null,
  xmltv_flags: { new: true, live: false, date: false },
  xmltv_video: { enabled: false, quality: "HDTV" },
  xmltv_categories: ["Sports", "Sports event"],
  xmltv_filler_categories: [],
  pregame_enabled: true,
  pregame_fallback: DEFAULT_PREGAME,
  postgame_enabled: true,
  postgame_fallback: DEFAULT_POSTGAME,
  // Legacy final/not-final conditionals ship disabled (#420): condition rows
  // are the mechanism; non-empty rows shadow the legacy dicts entirely.
  postgame_conditional: { enabled: false, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
  idle_enabled: true,
  idle_content: DEFAULT_IDLE,
  idle_conditional: { enabled: false, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
  // Recap-first postgame (#420, cajd.6): fires only when the provider
  // published a recap; otherwise the base constructed result line renders.
  // DEFAULT_FORM is event-typed; the type switch re-seeds the suffix flavor.
  pregame_conditional_rows: [],
  postgame_conditional_rows: seedPostgameRows(false),
  idle_conditional_rows: [],
  // Offseason register seeded enabled (#418): with it off, idle content
  // renders {*.next} literals once a team has no next scheduled game.
  // description_enabled is the master toggle; title unset falls back to the
  // idle title (no .next in it).
  idle_offseason: { title_enabled: false, title: null, subtitle_enabled: true, subtitle: "No upcoming game currently on schedule", description_enabled: true, description: "No upcoming {team_name} games scheduled." },
  conditional_descriptions: [],
  event_channel_name: "{matchup}",
  event_channel_logo_url: null,
}

// Default sample data (used before API loads)
export const DEFAULT_SAMPLE_DATA: Record<string, string> = {
  team_name: "Detroit Lions",
  opponent: "Chicago Bears",
  league: "NFL",
  sport: "Football",
}

// Mirror of the backend resolver's cleanup pass (resolver.py _cleanup_result,
// #354): empty-variable artifacts and the article-aware leading-"the"
// capitalization must render in the preview exactly as the engine emits them.
function cleanupResolved(text: string): string {
  let out = text.replace(/ {2,}/g, " ")
  out = out.replace(/ ?\( ?\)/g, "").replace(/ ?\[ ?\]/g, "")
  out = out.replace(/ {2,}/g, " ").trim()
  if (out.startsWith("the ")) out = "T" + out.slice(1)
  return out
}

// Accent fold for pascal/slug parity with the backend's NFKD+ascii pass.
function asciiFold(value: string): string {
  return value.normalize("NFKD").replace(/[̀-ͯ]/g, "")
}

// Template `|filter` modifiers, mirroring the backend registry
// (teamarr/templates/filters.py, #478/#484). Chains apply left-to-right:
// {team_name|pascal|url}. Kept in lockstep with the backend by
// tests/templates/test_filter_parity.py — add filters in BOTH places.
export const TEMPLATE_FILTERS: Record<string, (value: string) => string> = {
  urlencode: encodeURIComponent,
  url: encodeURIComponent,
  lower: (v) => v.toLowerCase(),
  upper: (v) => v.toUpperCase(),
  title: (v) => v.replace(/[A-Za-z]+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase()),
  pascal: (v) =>
    asciiFold(v)
      .split(/[^a-zA-Z0-9]+/)
      .filter(Boolean)
      .map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
      .join(""),
  slug: (v) =>
    asciiFold(v)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, ""),
}

// Retired pure-transform variables (#484): resolved forever as base+filter so
// pasted-in old templates still preview correctly (mirrors the backend
// resolver's _LEGACY_ALIASES). Exported for the picker's search bridge.
export const LEGACY_FILTER_ALIASES: Record<string, [string, string]> = {
  team_name_pascal: ["team_name", "pascal"],
  home_team_pascal: ["home_team", "pascal"],
  away_team_pascal: ["away_team", "pascal"],
  team_abbrev_lower: ["team_abbrev", "lower"],
  home_team_abbrev_lower: ["home_team_abbrev", "lower"],
  away_team_abbrev_lower: ["away_team_abbrev", "lower"],
  opponent_abbrev_lower: ["opponent_abbrev", "lower"],
  feed_team_abbrev_lower: ["feed_team_abbrev", "lower"],
  result_lower: ["result", "lower"],
  sport_lower: ["sport", "slug"],
}

// Helper to create resolveTemplate function with custom sample data.
// A known variable resolves to its value even when that value is empty (e.g.
// a pre-game {team_score.next}); only genuinely unknown variables stay literal.
export function createResolver(sampleData: Record<string, string>) {
  return function resolveTemplate(template: string): string {
    if (!template) return ""
    const substituted = template.replace(/\{([^}]+)\}/g, (match, token) => {
      // Split an optional `|filter` chain off the variable name (#484).
      const pipe = token.indexOf("|")
      let varName = pipe === -1 ? token : token.slice(0, pipe)
      const filterNames =
        pipe === -1 ? [] : token.slice(pipe + 1).toLowerCase().split("|").filter(Boolean)

      // Retired transform variable: rewrite to base + implied leading filter,
      // preserving any suffix ({home_team_pascal.next} -> home_team.next).
      const dot = varName.indexOf(".")
      const base = (dot === -1 ? varName : varName.slice(0, dot)).toLowerCase()
      const alias = LEGACY_FILTER_ALIASES[base]
      if (alias && !(varName in sampleData) && !(varName.toLowerCase() in sampleData)) {
        varName = alias[0] + (dot === -1 ? "" : varName.slice(dot))
        filterNames.unshift(alias[1])
      }

      let value: string
      if (varName in sampleData) value = sampleData[varName]
      else if (varName.toLowerCase() in sampleData) value = sampleData[varName.toLowerCase()]
      else return match // unknown variable stays literal

      for (const filterName of filterNames) {
        const filterFn = TEMPLATE_FILTERS[filterName]
        if (!filterFn) return match // unknown filter stays literal (visible typo)
        value = filterFn(value)
      }
      return value
    })
    return cleanupResolved(substituted)
  }
}
