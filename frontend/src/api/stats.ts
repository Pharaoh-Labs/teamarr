import { api } from "./client"

export interface LeagueCount {
  league: string
  count: number
}

export interface LiveStatsCategory {
  games_today: number
  live_now: number
  by_league: LeagueCount[]
}

export interface LiveStats {
  team: LiveStatsCategory
  event: LiveStatsCategory
}

export const statsApi = {
  getLiveStats: async (epgType?: "team" | "event"): Promise<LiveStats> => {
    const params = epgType ? `?epg_type=${epgType}` : ""
    return api.get(`/stats/live${params}`)
  },
}
