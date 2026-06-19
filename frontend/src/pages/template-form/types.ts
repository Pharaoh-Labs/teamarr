import type { TemplateCreate } from "@/api/templates"
import type { VariableCategory } from "@/api/variables"
import type { CachedLeague } from "@/api/teams"

export type Tab = "basic" | "defaults" | "conditions" | "fillers" | "xmltv"

export interface VariableSidebarProps {
  categories: VariableCategory[]
  onInsert: (varName: string) => void
  lastFocusedField: string | null
  isTeamTemplate: boolean
  leagues: CachedLeague[]
  subscribedSlugs: string[]
  previewLeague: string
  onLeagueChange: (league: string) => void
  liveRequested: boolean
  isLive: boolean
  onToggleLive: () => void
  /** Live coverage for the current event: how many relevant variables the real
   *  event populates vs. total relevant (gaps = relevant variables it can't
   *  fill). Null when not previewing live. */
  liveCoverage?: { populated: number; total: number; gaps: string[] } | null
}

export interface Variable {
  name: string
  description: string
  suffixes: string[]
}

export interface TabProps {
  formData: TemplateCreate
  setFormData: React.Dispatch<React.SetStateAction<TemplateCreate>>
  fieldRefs?: React.MutableRefObject<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>
  setLastFocusedField?: (field: string | null) => void
  isTeamTemplate?: boolean
  resolveTemplate: (template: string) => string
  validationData?: { validNames: Set<string>; baseNames: Set<string> }
}

// Template field with inline preview and validation
export interface TemplateFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  helpText?: string
  fieldRefs?: React.MutableRefObject<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>
  setLastFocusedField?: (field: string | null) => void
  multiline?: boolean
  resolveTemplate?: (template: string) => string
  validationData?: { validNames: Set<string>; baseNames: Set<string> }
  isEventTemplate?: boolean
  /** When true, render the resolved value as a live image so users can verify
   *  the art/gamethumb URL actually loads (with a broken-image state). */
  isImageField?: boolean
}
