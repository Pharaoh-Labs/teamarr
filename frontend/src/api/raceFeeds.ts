import { api } from "./client"

export type RaceFeedBehavior = "consolidate" | "separate" | "ignore"
export type RaceFeedKind = "driver" | "variant"

export interface RaceFeed {
  id: number
  league: string
  feed_key: string
  kind: RaceFeedKind
  label: string
  match_terms: string
  match_term_list: string[]
  behavior: RaceFeedBehavior
  enabled: boolean
  managed: boolean
  last_seen: string | null
}

export interface RaceFeedListResponse {
  league: string | null
  leagues: string[]
  feeds: RaceFeed[]
  total: number
}

export async function getRaceFeeds(league?: string): Promise<RaceFeedListResponse> {
  const qs = league ? `?league=${encodeURIComponent(league)}` : ""
  return api.get(`/race-feeds${qs}`)
}

export async function updateRaceFeed(
  id: number,
  data: { behavior?: RaceFeedBehavior; enabled?: boolean },
): Promise<RaceFeed> {
  return api.patch(`/race-feeds/${id}`, data)
}

export async function bulkRaceFeedBehavior(data: {
  league: string
  kind: RaceFeedKind
  behavior: RaceFeedBehavior
}): Promise<RaceFeedListResponse> {
  return api.post("/race-feeds/bulk", data)
}

export async function refreshRaceFeeds(league?: string): Promise<RaceFeedListResponse> {
  const qs = league ? `?league=${encodeURIComponent(league)}` : ""
  return api.post(`/race-feeds/refresh${qs}`)
}
