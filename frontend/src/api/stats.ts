import { api } from "./client"

export interface LeagueCount {
  league: string
  count: number
}

export interface LiveEvent {
  title: string
  channel_id: string
  start_time: string
  league: string
}

export interface LiveStatsCategory {
  games_today: number
  live_now: number
  by_league: LeagueCount[]
  live_events: LiveEvent[]
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

  clearAllRuns: async (): Promise<{ deleted: number; message: string }> => {
    return api.delete("/stats/runs")
  },

  getDatabaseStatus: async (): Promise<DatabaseStatus> => {
    return api.get("/stats/database")
  },

  compactDatabase: async (): Promise<CompactionState> => {
    return api.post("/stats/database/compact")
  },
}

export interface CompactionState {
  running: boolean
  started_at: string | null
  finished_at: string | null
  before_bytes: number | null
  after_bytes: number | null
  error: string | null
}

export interface DatabaseStatus {
  path: string
  file_bytes: number
  reclaimable_bytes: number
  run_count: number
  detail_rows: Record<string, number>
  compaction: CompactionState
}
