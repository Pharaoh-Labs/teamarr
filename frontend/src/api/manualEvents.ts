/**
 * Manual Events API (#1131).
 *
 * User-added team fixtures that supplement provider schedules so missing
 * games (preseason, unaired fixtures) still match streams and generate
 * temporary event channels. Identity is a stable `manual:<uuid>`; cancel is
 * a soft status change — normal generation owns all channel side effects.
 */
import { api } from "./client"

export interface ManualEventTeam {
  id: string
  provider: string
  name: string
  short_name: string
  abbreviation: string
  league: string
  sport: string
  logo_url: string | null
}

export interface ManualEventStatus {
  state: "scheduled" | "cancelled"
  detail: string | null
}

export interface ManualEvent {
  id: string
  name: string
  short_name: string
  /** ISO 8601 UTC instant. */
  start_time: string
  league: string
  season_type: string | null
  neutral_site: boolean
  venue: { name: string } | null
  home_team: ManualEventTeam
  away_team: ManualEventTeam
  status: ManualEventStatus
}

export interface ManualEventInput {
  league: string
  home_team: { provider: string; id: string }
  away_team: { provider: string; id: string }
  /** ISO 8601 with offset — the browser's local offset is fine. */
  start_time: string
  name?: string | null
  venue?: string | null
  season_type?: "preseason" | "regular" | "postseason"
  neutral_site?: boolean
}

export async function listManualEvents(): Promise<{ events: ManualEvent[]; total: number }> {
  return api.get("/manual-events")
}

export interface DuplicatePair {
  manual: ManualEvent
  upstream: ManualEvent
}

export async function listDuplicates(): Promise<{ duplicates: DuplicatePair[]; total: number }> {
  return api.get("/manual-events/duplicates")
}

export async function createManualEvent(data: ManualEventInput): Promise<ManualEvent> {
  return api.post("/manual-events", data)
}

export async function updateManualEvent(
  eventId: string,
  data: ManualEventInput
): Promise<ManualEvent> {
  return api.put(`/manual-events/${encodeURIComponent(eventId)}`, data)
}

export async function cancelManualEvent(eventId: string, league: string): Promise<ManualEvent> {
  return api.delete(`/manual-events/${encodeURIComponent(eventId)}?league=${encodeURIComponent(league)}`)
}
