import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"

/**
 * Conference (provider group) filtering for a league (#91).
 *
 * Shared by the Team Importer and TeamPicker so both label, sort, and count
 * conferences identically — the two browsers are deliberately separate
 * components (different fetch models, payloads, and selection semantics),
 * but their conference behavior must not drift.
 *
 * Only NCAA football/basketball return groups; every other league yields an
 * empty list, and callers hide the control.
 */

export interface LeagueConference {
  key: string
  name: string
  abbrev: string | null
  season: number | null
  team_count: number
  team_ids: string[]
}

export async function fetchConferencesForLeague(
  league: string
): Promise<LeagueConference[]> {
  const result = await api.get<LeagueConference[]>(
    `/cache/leagues/${league}/conferences`
  )
  return Array.isArray(result) ? result : []
}

/** Display label for a conference option: "SEC — Southeastern Conference (16)". */
export function conferenceLabel(conf: LeagueConference): string {
  const name = conf.abbrev ? `${conf.abbrev} — ${conf.name}` : conf.name
  return `${name} (${conf.team_count})`
}

const EMPTY: LeagueConference[] = []

export function useConferenceFilter(league: string | null | undefined) {
  const [selectedConference, setSelectedConference] = useState<string>("")

  const query = useQuery({
    queryKey: ["cache-league-conferences", league],
    queryFn: () => fetchConferencesForLeague(league!),
    enabled: !!league,
    staleTime: 10 * 60 * 1000,
  })

  // Memoized so the empty-list fallback isn't a new array every render
  const conferences = useMemo(() => query.data ?? EMPTY, [query.data])

  /** Member team ids of the active conference, or null when unfiltered. */
  const conferenceTeamIds = useMemo(() => {
    if (!selectedConference) return null
    const conf = conferences.find((c) => c.key === selectedConference)
    return conf ? new Set(conf.team_ids) : null
  }, [conferences, selectedConference])

  const reset = () => setSelectedConference("")

  return {
    conferences,
    selectedConference,
    setSelectedConference,
    conferenceTeamIds,
    reset,
    isLoading: query.isLoading,
  }
}
