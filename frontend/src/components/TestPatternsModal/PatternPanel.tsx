/**
 * PatternPanel — regex input fields that mirror the EventGroupForm.
 *
 * Shows the same fields the form has: skip_builtin, include/exclude,
 * plus extraction patterns organized by event type (Team vs Team, Combat/Event Card).
 * Each field has an enable checkbox and a text input. Validation feedback is shown inline.
 */

import { useState, useCallback } from "react"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { validateRegex } from "@/lib/regex-utils"
import type { PatternState } from "./index"
import {
  ShieldOff,
  Filter,
  FilterX,
  Users,
  Calendar,
  Clock,
  Trophy,
  Swords,
  Tag,
} from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PatternPanelProps {
  patterns: PatternState
  onChange: (update: Partial<PatternState>) => void
}

type EventTypeTab = "team_vs_team" | "event_card"

// ---------------------------------------------------------------------------
// Field config
// ---------------------------------------------------------------------------

interface FieldConfig {
  patternKey: keyof PatternState
  enabledKey: keyof PatternState
  label: string
  placeholder: string
  icon: React.ReactNode
  color: string
}

// Stream filtering fields (always shown)
const FILTER_FIELDS: FieldConfig[] = [
  {
    patternKey: "stream_include_regex",
    enabledKey: "stream_include_regex_enabled",
    label: "Include Pattern",
    placeholder: 'e.g., Gonzaga|Washington State',
    icon: <Filter className="h-3.5 w-3.5" />,
    color: "text-success",
  },
  {
    patternKey: "stream_exclude_regex",
    enabledKey: "stream_exclude_regex_enabled",
    label: "Exclude Pattern",
    placeholder: 'e.g., \\(ES\\)|\\(ALT\\)|All.?Star',
    icon: <FilterX className="h-3.5 w-3.5" />,
    color: "text-destructive",
  },
]

// Team vs Team extraction fields (excluding date — rendered separately with sub-fields)
const TEAM_VS_TEAM_FIELDS: FieldConfig[] = [
  {
    patternKey: "custom_regex_teams",
    enabledKey: "custom_regex_teams_enabled",
    label: "Teams Extraction",
    placeholder: '(?P<team1>...) vs (?P<team2>...)',
    icon: <Users className="h-3.5 w-3.5" />,
    color: "text-blue-400",
  },
]

const AFTER_DATE_TEAM_FIELDS: FieldConfig[] = [
  {
    patternKey: "custom_regex_time",
    enabledKey: "custom_regex_time_enabled",
    label: "Time Extraction",
    placeholder: '(?P<time>\\d{1,2}:\\d{2}\\s*(?:AM|PM)?)',
    icon: <Clock className="h-3.5 w-3.5" />,
    color: "text-orange-400",
  },
  {
    patternKey: "custom_regex_league",
    enabledKey: "custom_regex_league_enabled",
    label: "League Extraction",
    placeholder: '(?P<league>NHL|NBA|NFL|MLB)',
    icon: <Trophy className="h-3.5 w-3.5" />,
    color: "text-purple-400",
  },
]

// Combat / Event Card extraction fields (excluding date — rendered separately)
const EVENT_CARD_FIELDS: FieldConfig[] = [
  {
    patternKey: "custom_regex_fighters",
    enabledKey: "custom_regex_fighters_enabled",
    label: "Fighters Extraction",
    placeholder: '(?P<fighters>\\w+ vs \\w+)',
    icon: <Swords className="h-3.5 w-3.5" />,
    color: "text-red-400",
  },
  {
    patternKey: "custom_regex_event_name",
    enabledKey: "custom_regex_event_name_enabled",
    label: "Event Name Extraction",
    placeholder: '(?P<event_name>UFC \\d+|Fight Night)',
    icon: <Tag className="h-3.5 w-3.5" />,
    color: "text-cyan-400",
  },
]

const AFTER_DATE_EVENT_FIELDS: FieldConfig[] = [
  {
    patternKey: "custom_regex_time",
    enabledKey: "custom_regex_time_enabled",
    label: "Time Extraction",
    placeholder: '(?P<time>\\d{1,2}:\\d{2}\\s*(?:AM|PM)?)',
    icon: <Clock className="h-3.5 w-3.5" />,
    color: "text-orange-400",
  },
]

// Date sub-field configs
const DATE_FIELD: FieldConfig = {
  patternKey: "custom_regex_date",
  enabledKey: "custom_regex_date_enabled",
  label: "Date Extraction",
  placeholder: '(?P<day>\\d{1,2})/(?P<month>\\d{1,2})/(?P<year>\\d{2,4})',
  icon: <Calendar className="h-3.5 w-3.5" />,
  color: "text-yellow-400",
}

const MONTH_FIELD: FieldConfig = {
  patternKey: "custom_regex_month",
  enabledKey: "custom_regex_month_enabled",
  label: "Month",
  placeholder: '(?P<month>\\w+)',
  icon: <Calendar className="h-3 w-3" />,
  color: "text-yellow-400/70",
}

const DAY_FIELD: FieldConfig = {
  patternKey: "custom_regex_day",
  enabledKey: "custom_regex_day_enabled",
  label: "Day",
  placeholder: '(?P<day>\\d{1,2})',
  icon: <Calendar className="h-3 w-3" />,
  color: "text-yellow-400/70",
}

// ---------------------------------------------------------------------------
// Field Renderer
// ---------------------------------------------------------------------------

function renderField(
  field: FieldConfig,
  patterns: PatternState,
  handleToggle: (key: keyof PatternState) => void,
  handleChange: (key: keyof PatternState, value: string) => void
) {
  const pattern = (patterns[field.patternKey] as string) || ""
  const enabled = patterns[field.enabledKey] as boolean
  const validation = pattern ? validateRegex(pattern) : null

  return (
    <div key={field.patternKey} className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Checkbox
          checked={enabled}
          onCheckedChange={() => handleToggle(field.enabledKey)}
        />
        <span className={cn("flex items-center gap-1 text-xs font-medium", field.color)}>
          {field.icon}
          {field.label}
        </span>
        {validation && !validation.valid && (
          <span className="text-xs text-destructive ml-auto truncate max-w-[200px]">
            {validation.error}
          </span>
        )}
        {validation?.valid && enabled && (
          <span className="text-xs text-success ml-auto">Valid</span>
        )}
      </div>
      <Input
        value={pattern}
        onChange={(e) => handleChange(field.patternKey, e.target.value)}
        placeholder={field.placeholder}
        className={cn(
          "text-xs font-mono h-7",
          !enabled && "opacity-50"
        )}
      />
    </div>
  )
}

/**
 * Renders the Date extraction field with Month and Day sub-options.
 * Sub-options are always visible but indented to show they're alternatives.
 */
function renderDateSection(
  patterns: PatternState,
  handleToggle: (key: keyof PatternState) => void,
  handleChange: (key: keyof PatternState, value: string) => void
) {
  const datePattern = (patterns.custom_regex_date as string) || ""
  const dateEnabled = patterns.custom_regex_date_enabled as boolean
  const dateValidation = datePattern ? validateRegex(datePattern) : null

  const monthPattern = (patterns.custom_regex_month as string) || ""
  const monthEnabled = patterns.custom_regex_month_enabled as boolean
  const monthValidation = monthPattern ? validateRegex(monthPattern) : null

  const dayPattern = (patterns.custom_regex_day as string) || ""
  const dayEnabled = patterns.custom_regex_day_enabled as boolean
  const dayValidation = dayPattern ? validateRegex(dayPattern) : null

  return (
    <div key="date-section" className="flex flex-col gap-1">
      {/* Main date field */}
      <div className="flex items-center gap-2">
        <Checkbox
          checked={dateEnabled}
          onCheckedChange={() => handleToggle("custom_regex_date_enabled")}
        />
        <span className={cn("flex items-center gap-1 text-xs font-medium", DATE_FIELD.color)}>
          {DATE_FIELD.icon}
          {DATE_FIELD.label}
        </span>
        {dateValidation && !dateValidation.valid && (
          <span className="text-xs text-destructive ml-auto truncate max-w-[200px]">
            {dateValidation.error}
          </span>
        )}
        {dateValidation?.valid && dateEnabled && (
          <span className="text-xs text-success ml-auto">Valid</span>
        )}
      </div>
      <Input
        value={datePattern}
        onChange={(e) => handleChange("custom_regex_date", e.target.value)}
        placeholder={DATE_FIELD.placeholder}
        className={cn(
          "text-xs font-mono h-7",
          !dateEnabled && "opacity-50"
        )}
      />

      {/* Month/Day sub-options — indented */}
      <div className="ml-5 pl-2 border-l border-border/50 space-y-1 mt-1">
        <div className="text-[10px] text-muted-foreground uppercase tracking-wide">
          Or extract separately
        </div>

        {/* Month */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Checkbox
              checked={monthEnabled}
              onCheckedChange={() => handleToggle("custom_regex_month_enabled")}
            />
            <span className={cn("flex items-center gap-1 text-xs font-medium", MONTH_FIELD.color)}>
              {MONTH_FIELD.icon}
              {MONTH_FIELD.label}
            </span>
            {monthValidation && !monthValidation.valid && (
              <span className="text-xs text-destructive ml-auto truncate max-w-[150px]">
                {monthValidation.error}
              </span>
            )}
            {monthValidation?.valid && monthEnabled && (
              <span className="text-xs text-success ml-auto">Valid</span>
            )}
          </div>
          <Input
            value={monthPattern}
            onChange={(e) => handleChange("custom_regex_month", e.target.value)}
            placeholder={MONTH_FIELD.placeholder}
            className={cn(
              "text-xs font-mono h-7",
              !monthEnabled && "opacity-50"
            )}
          />
        </div>

        {/* Day */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Checkbox
              checked={dayEnabled}
              onCheckedChange={() => handleToggle("custom_regex_day_enabled")}
            />
            <span className={cn("flex items-center gap-1 text-xs font-medium", DAY_FIELD.color)}>
              {DAY_FIELD.icon}
              {DAY_FIELD.label}
            </span>
            {dayValidation && !dayValidation.valid && (
              <span className="text-xs text-destructive ml-auto truncate max-w-[150px]">
                {dayValidation.error}
              </span>
            )}
            {dayValidation?.valid && dayEnabled && (
              <span className="text-xs text-success ml-auto">Valid</span>
            )}
          </div>
          <Input
            value={dayPattern}
            onChange={(e) => handleChange("custom_regex_day", e.target.value)}
            placeholder={DAY_FIELD.placeholder}
            className={cn(
              "text-xs font-mono h-7",
              !dayEnabled && "opacity-50"
            )}
          />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PatternPanel({ patterns, onChange }: PatternPanelProps) {
  const [eventType, setEventType] = useState<EventTypeTab>("team_vs_team")

  const handleToggle = useCallback(
    (key: keyof PatternState) => {
      onChange({ [key]: !patterns[key] })
    },
    [patterns, onChange]
  )

  const handleChange = useCallback(
    (key: keyof PatternState, value: string) => {
      onChange({ [key]: value || null })
    },
    [onChange]
  )

  // Get the extraction fields for the current event type
  const beforeDateFields = eventType === "team_vs_team" ? TEAM_VS_TEAM_FIELDS : EVENT_CARD_FIELDS
  const afterDateFields = eventType === "team_vs_team" ? AFTER_DATE_TEAM_FIELDS : AFTER_DATE_EVENT_FIELDS

  return (
    <div className="flex flex-col gap-2 p-3">
      {/* Skip built-in filter toggle */}
      <div className="flex items-center gap-2 pb-2 border-b border-border">
        <Checkbox
          checked={patterns.skip_builtin_filter}
          onCheckedChange={() =>
            onChange({ skip_builtin_filter: !patterns.skip_builtin_filter })
          }
        />
        <ShieldOff className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">
          Skip built-in filters
        </span>
      </div>

      {/* Stream Filter Patterns (always shown) */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Stream Filtering
        </div>
        {FILTER_FIELDS.map((field) =>
          renderField(field, patterns, handleToggle, handleChange)
        )}
      </div>

      {/* Extraction Patterns by Event Type */}
      <div className="space-y-2 pt-2 border-t border-border">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Extraction Patterns
        </div>

        {/* Event Type Tabs */}
        <div className="flex gap-1 p-1 bg-muted rounded-lg">
          <button
            type="button"
            onClick={() => setEventType("team_vs_team")}
            className={cn(
              "flex-1 px-2 py-1 text-xs font-medium rounded transition-colors",
              eventType === "team_vs_team"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Team vs Team
          </button>
          <button
            type="button"
            onClick={() => setEventType("event_card")}
            className={cn(
              "flex-1 px-2 py-1 text-xs font-medium rounded transition-colors",
              eventType === "event_card"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Combat / Event Card
          </button>
        </div>

        {/* Extraction fields: before date → date section → after date */}
        <div className="space-y-2">
          {beforeDateFields.map((field) =>
            renderField(field, patterns, handleToggle, handleChange)
          )}
          {renderDateSection(patterns, handleToggle, handleChange)}
          {afterDateFields.map((field) =>
            renderField(field, patterns, handleToggle, handleChange)
          )}
        </div>
      </div>
    </div>
  )
}
