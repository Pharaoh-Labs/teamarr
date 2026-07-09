import { useState, useCallback } from "react"
import { toast } from "sonner"
import {
  searchEvents,
  correctStreamMatch,
} from "@/api/epg"
import type { FailedMatch, MatchedStream, EventSearchResult, CorrectableStream } from "@/api/epg"

export function useEventMatcher() {
  const [open, setOpen] = useState(false)
  const [stream, setStream] = useState<CorrectableStream | null>(null)
  const [league, setLeague] = useState("")
  const [targetDate, setTargetDate] = useState(() => {
    return new Date().toISOString().split("T")[0]
  })
  const [teamFilter, setTeamFilter] = useState("")
  const [events, setEvents] = useState<EventSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

  const handleOpen = useCallback((incoming: FailedMatch | MatchedStream) => {
    const correctable: CorrectableStream = {
      group_id: incoming.group_id,
      stream_id: incoming.stream_id,
      stream_name: incoming.stream_name,
      group_name: incoming.group_name,
      league_hint: "detected_league" in incoming ? incoming.detected_league : incoming.league,
      current_event_id: "event_id" in incoming ? incoming.event_id : null,
    }
    setStream(correctable)
    setLeague(correctable.league_hint ?? "")
    setTeamFilter("")
    setEvents([])
    setSelectedEventId(null)
    setOpen(true)
  }, [])

  const handleSearch = useCallback(async () => {
    if (!league) return
    setLoading(true)
    try {
      const result = await searchEvents(league, teamFilter || undefined, targetDate || undefined, 50)
      setEvents(result.events)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to search events")
    } finally {
      setLoading(false)
    }
  }, [league, teamFilter, targetDate])

  const handleCorrect = useCallback(async () => {
    if (!stream || !selectedEventId || !league) return
    if (stream.stream_id === null) {
      toast.error("Cannot correct: stream_id is missing")
      return
    }
    setSubmitting(true)
    try {
      await correctStreamMatch({
        group_id: stream.group_id,
        stream_id: stream.stream_id,
        stream_name: stream.stream_name,
        correct_event_id: selectedEventId,
        correct_league: league,
      })
      toast.success("Stream matched to event", {
        description: "Changes will apply on next EPG generation",
      })
      setOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to apply correction")
    } finally {
      setSubmitting(false)
    }
  }, [stream, selectedEventId, league])

  const handleSkip = useCallback(async () => {
    if (!stream) return
    if (stream.stream_id === null) {
      toast.error("Cannot correct: stream_id is missing")
      return
    }
    setSubmitting(true)
    try {
      await correctStreamMatch({
        group_id: stream.group_id,
        stream_id: stream.stream_id,
        stream_name: stream.stream_name,
        correct_event_id: null,
        correct_league: null,
      })
      toast.success("Stream marked as 'no event'", {
        description: "Changes will apply on next EPG generation",
      })
      setOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to mark as no event")
    } finally {
      setSubmitting(false)
    }
  }, [stream])

  return {
    open,
    setOpen,
    stream,
    league,
    setLeague,
    targetDate,
    setTargetDate,
    teamFilter,
    setTeamFilter,
    events,
    loading,
    submitting,
    selectedEventId,
    setSelectedEventId,
    handleOpen,
    handleSearch,
    handleCorrect,
    handleSkip,
  }
}
