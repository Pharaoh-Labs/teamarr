import { api } from "./client"

export interface Variable {
  name: string
  description: string
  suffixes: string[]
}

export interface VariableCategory {
  name: string
  variables: Variable[]
}

export interface VariablesResponse {
  total: number
  template_type: string | null
  categories: VariableCategory[]
  available_sports: string[]
}

export interface SamplesResponse {
  sport: string
  league?: string | null
  live?: boolean
  available_sports: string[]
  samples: Record<string, string>
}

export interface Condition {
  name: string
  description: string
  requires_value: boolean
  value_type?: "number" | "string"
  providers?: "all" | "espn"  // "all" = universal, "espn" = ESPN leagues only
}

export interface ConditionsResponse {
  conditions: Condition[]
}

export async function fetchVariables(
  templateType?: "team" | "event",
): Promise<VariablesResponse> {
  const qs = templateType ? `?template_type=${encodeURIComponent(templateType)}` : ""
  return api.get(`/variables${qs}`)
}

export async function fetchConditions(templateType: string = "team"): Promise<ConditionsResponse> {
  return api.get(`/variables/conditions?template_type=${encodeURIComponent(templateType)}`)
}

export interface SampleLeague {
  slug: string
  name: string
  sport: string
  logo_url: string | null
}

interface LeaguesListResponse {
  count: number
  leagues: SampleLeague[]
}

// Leagues available to preview templates against, grouped by sport in the UI.
export async function fetchSampleLeagues(): Promise<SampleLeague[]> {
  const data = await api.get<LeaguesListResponse>("/leagues")
  return data.leagues
}

export async function fetchSamples(
  sportOrLeague: string = "NBA",
  opts?: { byLeague?: boolean; live?: boolean },
): Promise<SamplesResponse> {
  const params = new URLSearchParams()
  if (opts?.byLeague) {
    params.set("league", sportOrLeague)
  } else {
    params.set("sport", sportOrLeague)
  }
  if (opts?.live) params.set("live", "true")
  return api.get(`/variables/samples?${params.toString()}`)
}
