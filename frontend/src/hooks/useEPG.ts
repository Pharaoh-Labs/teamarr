import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getStats,
  getRecentRuns,
  getCacheStatus,
  refreshCache,
  getEPGAnalysis,
  getEPGContent,
  getGameDataCacheStats,
  clearGameDataCache,
} from "@/api/epg"
import { clearAllMatchCache, getMatchCacheStats } from "@/api/groups"
import { statsApi } from "@/api/stats"

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
    refetchInterval: 30000, // Refresh every 30s
  })
}

export function useRecentRuns(limit = 20, runType?: string) {
  return useQuery({
    queryKey: ["runs", { limit, runType }],
    queryFn: () => getRecentRuns(limit, runType),
    refetchInterval: 30000,
  })
}

export function useCacheStatus() {
  return useQuery({
    queryKey: ["cacheStatus"],
    queryFn: getCacheStatus,
    refetchInterval: 10000, // Check cache status every 10s
  })
}

export function useRefreshCache() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: refreshCache,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cacheStatus"] })
    },
  })
}

export function useEPGAnalysis() {
  return useQuery({
    queryKey: ["epgAnalysis"],
    queryFn: getEPGAnalysis,
    staleTime: 60000, // Consider stale after 1 minute
  })
}

export function useEPGContent(maxLines = 2000) {
  return useQuery({
    queryKey: ["epgContent", maxLines],
    queryFn: () => getEPGContent(maxLines),
    staleTime: 60000,
  })
}

// Game Data Cache hooks (schedules, scores, odds)

export function useGameDataCacheStats() {
  return useQuery({
    queryKey: ["gameDataCacheStats"],
    queryFn: getGameDataCacheStats,
    refetchInterval: 30000, // Refresh every 30s
  })
}

export function useClearGameDataCache() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clearGameDataCache,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gameDataCacheStats"] })
    },
  })
}

// Run History Cleanup

export function useClearAllRuns() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => statsApi.clearAllRuns(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] })
    },
  })
}

// Stream Match Cache

export function useMatchCacheStats() {
  return useQuery({
    queryKey: ["matchCacheStats"],
    queryFn: getMatchCacheStats,
    refetchInterval: 30000,
  })
}

export function useClearAllMatchCache() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: clearAllMatchCache,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matchCacheStats"] })
    },
  })
}
