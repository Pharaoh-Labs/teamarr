import { useGroups } from "@/hooks/useGroups"

export interface MatchRate {
  matched: number
  failed: number
  /** Rounded 0–100 percentage of eligible streams that matched an event. */
  rate: number
  /** True when there was at least one match attempt to report a rate for. */
  hasData: boolean
}

/**
 * The single source of truth for the overall stream→event match rate, shared by
 * the Sources page and the Dashboard status strip so they never disagree.
 *
 * Definition: matched / (matched + failed) across all sources — i.e. the share
 * of *eligible* streams that matched. Streams removed by filtering or exclusion
 * are not in the denominator (that breakdown lives in the generation logs).
 *
 * Backed by the shared ["groups"] query, so it reuses the cache rather than
 * issuing a separate fetch.
 */
export function useMatchRate(): MatchRate {
  const { data } = useGroups(true)
  const groups = data?.groups ?? []
  const matched = groups.reduce((sum, g) => sum + (g.matched_count || 0), 0)
  const failed = groups.reduce((sum, g) => sum + (g.failed_count || 0), 0)
  const attempted = matched + failed
  return {
    matched,
    failed,
    rate: attempted > 0 ? Math.round((matched / attempted) * 100) : 0,
    hasData: attempted > 0,
  }
}

/** Tailwind text-color class for a match rate, shared for consistent thresholds. */
export function matchRateColor(rate: number): string {
  if (rate >= 85) return "text-green-500"
  if (rate >= 60) return "text-orange-500"
  if (rate > 0) return "text-red-500"
  return "text-muted-foreground"
}
