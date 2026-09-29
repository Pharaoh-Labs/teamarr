import type { KeywordMatchSources } from "@/api/settings"

export const EMPTY_SOURCES: KeywordMatchSources = {
  m3u_group_pattern: null,
  m3u_groups: [],
  stream_pattern: null,
  streams: [],
  event_group_ids: [],
}

/** How many sources beyond match terms a keyword has, for the row summary. */
export function countSources(s: KeywordMatchSources): number {
  return (
    (s.m3u_group_pattern ? 1 : 0) +
    (s.stream_pattern ? 1 : 0) +
    s.m3u_groups.length +
    s.streams.length +
    s.event_group_ids.length
  )
}
