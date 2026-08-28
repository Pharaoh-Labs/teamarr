import { api } from "./client"

// Pinned channel-number blocks (#333). A block numbers a team / league / sport
// from a fixed start; rows sharing start + label form a group. Everything
// unmatched numbers from the global channel range.

export type NumberingScope = "team" | "league" | "sport"

export interface NumberingException {
  id: number
  scope: NumberingScope
  sport: string
  league_code: string | null
  team_name: string | null
  provider: string | null
  provider_team_id: string | null
  start: number
  end: number | null
  label: string | null
  sort_order: number
  enabled: boolean
  display_name: string | null
  channel_count: number
}

export interface NumberingExceptionCreate {
  scope: NumberingScope
  start: number
  end?: number | null
  label?: string | null
  sport?: string | null
  league_code?: string | null
  provider?: string | null
  team_id?: string | null
  team_league?: string | null
}

export interface NumberingExceptionUpdate {
  start?: number
  end?: number | null
  clear_end?: boolean
  label?: string | null
  clear_label?: boolean
  enabled?: boolean
}

export interface LanePreview {
  id: number | null // null = default range
  label: string
  start: number
  end: number | null
  channel_count: number
  first_number: number | null
  last_number: number | null
  spills_into_next: boolean
}

export async function getNumberingExceptions(): Promise<NumberingException[]> {
  return api.get("/numbering-exceptions")
}

export async function createNumberingException(
  data: NumberingExceptionCreate
): Promise<NumberingException> {
  return api.post("/numbering-exceptions", data)
}

export async function updateNumberingException(
  id: number,
  data: NumberingExceptionUpdate
): Promise<NumberingException> {
  return api.put(`/numbering-exceptions/${id}`, data)
}

export async function deleteNumberingException(id: number): Promise<{ success: boolean }> {
  return api.delete(`/numbering-exceptions/${id}`)
}

export async function reorderNumberingExceptions(
  orderedIds: number[]
): Promise<{ success: boolean }> {
  return api.put("/numbering-exceptions/reorder", { ordered_ids: orderedIds })
}

export async function getNumberingPreview(): Promise<LanePreview[]> {
  return api.get("/numbering-exceptions/preview")
}
