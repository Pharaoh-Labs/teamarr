import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  bulkRaceFeedBehavior,
  getRaceFeeds,
  refreshRaceFeeds,
  updateRaceFeed,
  type RaceFeedBehavior,
  type RaceFeedKind,
} from "@/api/raceFeeds"

const KEY = ["race-feeds"] as const

export function useRaceFeeds(league?: string) {
  return useQuery({
    queryKey: [...KEY, { league: league ?? null }],
    queryFn: () => getRaceFeeds(league),
  })
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: KEY })
}

export function useUpdateRaceFeed() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; behavior?: RaceFeedBehavior; enabled?: boolean }) =>
      updateRaceFeed(id, data),
    onSuccess: invalidate,
  })
}

export function useBulkRaceFeedBehavior() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (data: { league: string; kind: RaceFeedKind; behavior: RaceFeedBehavior }) =>
      bulkRaceFeedBehavior(data),
    onSuccess: invalidate,
  })
}

export function useRefreshRaceFeeds() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (league?: string) => refreshRaceFeeds(league),
    onSuccess: invalidate,
  })
}
