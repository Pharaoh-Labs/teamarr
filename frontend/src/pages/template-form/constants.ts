import type { LucideIcon } from "lucide-react"
import { ClipboardList, Pencil, Target, Calendar, Settings } from "lucide-react"
import type { TemplateCreate, FillerContent } from "@/api/templates"
import type { Tab } from "./types"

export const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "basic", label: "Basics", icon: ClipboardList },
  { id: "defaults", label: "Defaults", icon: Pencil },
  { id: "conditions", label: "Conditions", icon: Target },
  { id: "fillers", label: "Fillers", icon: Calendar },
  { id: "xmltv", label: "EPG Options", icon: Settings },
]

// Default filler content
export const DEFAULT_PREGAME: FillerContent = {
  title: "Coming up: {league} {sport} starting at {game_time.next}",
  subtitle: "{away_team} at {home_team}",
  description: "The {away_team_record.next} {away_team.next} travel to {venue_city} to play the {home_team_record.next} {home_team.next} today at {game_time.next}.",
  art_url: null,
}

export const DEFAULT_POSTGAME: FillerContent = {
  title: "{league} {sport}: {team_name} Postgame Recap",
  subtitle: "{away_team.last} at {home_team.last}",
  description: "{team_name} {result_text.last} the {opponent.last} {final_score.last}",
  art_url: null,
}

export const DEFAULT_IDLE: FillerContent = {
  title: "No {team_name} Game Today",
  subtitle: "Next game: {game_date.next} at {game_time.next} {vs_at.next} the {opponent.next}",
  description: "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
  art_url: null,
}

export const DEFAULT_FORM: TemplateCreate = {
  name: "",
  // Event templates are the primary focus, so new templates default to "event"
  // (pre-selected in the create type chooser).
  template_type: "event",
  title_format: "{league} {sport}",
  subtitle_template: "{away_team} at {home_team}",
  description_template: "{matchup} | {venue_full}",
  program_art_url: null,
  game_duration_mode: "sport",
  game_duration_override: null,
  xmltv_flags: { new: true, live: false, date: false },
  xmltv_video: { enabled: false, quality: "HDTV" },
  xmltv_categories: ["Sports"],
  xmltv_filler_categories: [],
  pregame_enabled: true,
  pregame_fallback: DEFAULT_PREGAME,
  postgame_enabled: true,
  postgame_fallback: DEFAULT_POSTGAME,
  postgame_conditional: { enabled: true, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
  idle_enabled: true,
  idle_content: DEFAULT_IDLE,
  idle_conditional: { enabled: true, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
  // Offseason register seeded enabled (#418): with it off, idle content
  // renders {*.next} literals once a team has no next scheduled game.
  // description_enabled is the master toggle; title unset falls back to the
  // idle title (no .next in it).
  idle_offseason: { title_enabled: false, title: null, subtitle_enabled: true, subtitle: "No upcoming game currently on schedule", description_enabled: true, description: "No upcoming {team_name} games scheduled." },
  conditional_descriptions: [],
  event_channel_name: "{away_team} @ {home_team}",
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

// Helper to create resolveTemplate function with custom sample data.
// A known variable resolves to its value even when that value is empty (e.g.
// a pre-game {team_score.next}); only genuinely unknown variables stay literal.
export function createResolver(sampleData: Record<string, string>) {
  return function resolveTemplate(template: string): string {
    if (!template) return ""
    const substituted = template.replace(/\{([^}]+)\}/g, (match, varName) => {
      if (varName in sampleData) return sampleData[varName]
      const lower = varName.toLowerCase()
      if (lower in sampleData) return sampleData[lower]
      return match
    })
    return cleanupResolved(substituted)
  }
}
