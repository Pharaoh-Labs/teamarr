import { api } from "./client"
import type { CachedLeague } from "./teams"

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
  // Live-only: variable names the real event couldn't populate (surfaced as
  // gaps instead of masked with the fictitious sample), plus coverage counts.
  gaps?: string[]
  live_populated?: number | null
  live_total?: number | null
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

export interface SampleLeaguesResponse {
  count: number
  leagues: CachedLeague[]
  subscribed_slugs: string[]
}

// Leagues for the template preview selector: all enabled leagues, plus which
// slugs the user is subscribed to. The picker defaults to the subscribed subset
// but can search the full list.
export async function fetchSampleLeagues(): Promise<SampleLeaguesResponse> {
  return api.get<SampleLeaguesResponse>("/variables/sample-leagues")
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
