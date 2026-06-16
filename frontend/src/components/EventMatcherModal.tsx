/**
 * EventMatcherModal — reusable modal for manually correcting stream-to-event matches.
 *
 * Used by both the Dashboard and EPG pages when clicking failed/matched streams.
 * Provides league selection, date picker, event search, and correction/skip actions.
 */

import { useState, useMemo, useCallback } from "react"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import { Loader2, XCircle, Search, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  searchEvents,
  correctStreamMatch,
} from "@/api/epg"
import { getLeagues } from "@/api/teams"
import type { FailedMatch, MatchedStream, EventSearchResult, CorrectableStream } from "@/api/epg"
import type { CachedLeague } from "@/api/teams"
import { getLeagueDisplayName } from "@/lib/utils"
import { useDateFormat } from "@/hooks/useDateFormat"

// ---------------------------------------------------------------------------
// Hook — manages all event matcher state and actions
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface EventMatcherModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  stream: CorrectableStream | null
  league: string
  onLeagueChange: (league: string) => void
  targetDate: string
  onTargetDateChange: (date: string) => void
  teamFilter: string
  onTeamFilterChange: (value: string) => void
  events: EventSearchResult[]
  loading: boolean
  submitting: boolean
  selectedEventId: string | null
  onSelectEvent: (eventId: string) => void
  onSearch: () => void
  onCorrect: () => void
  onSkip: () => void
}

export function EventMatcherModal({
  open,
  onOpenChange,
  stream,
  league,
  onLeagueChange,
  targetDate,
  onTargetDateChange,
  teamFilter,
  onTeamFilterChange,
  events,
  loading,
  submitting,
  selectedEventId,
  onSelectEvent,
  onSearch,
  onCorrect,
  onSkip,
}: EventMatcherModalProps) {
  const { formatDateTime } = useDateFormat()

  const { data: leaguesData, isLoading: leaguesLoading } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(false),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })

  const sortedLeagues = useMemo(() => {
    if (!leaguesData?.leagues) return []
    return [...leaguesData.leagues].sort((a, b) => {
      const sportCompare = (a.sport ?? "").localeCompare(b.sport ?? "")
      if (sportCompare !== 0) return sportCompare
      return (a.name ?? a.slug ?? "").localeCompare(b.name ?? b.slug ?? "")
    })
  }, [leaguesData?.leagues])

  const leaguesBySport = useMemo(() => {
    const grouped: Record<string, CachedLeague[]> = {}
    for (const l of sortedLeagues) {
      const sport = l.sport ?? "Unknown"
      if (!grouped[sport]) grouped[sport] = []
      grouped[sport].push(l)
    }
    return grouped
  }, [sortedLeagues])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl h-[80vh] flex flex-col" onClose={() => onOpenChange(false)}>
        <DialogHeader>
          <DialogTitle>
            {stream?.current_event_id ? "Correct Stream Match" : "Match Stream to Event"}
          </DialogTitle>
          <DialogDescription>
            {stream?.current_event_id
              ? "This stream is currently matched incorrectly. Select the correct event or skip it."
              : "Select the correct event for this stream, or skip it if it shouldn't match."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4 flex-1 overflow-hidden flex flex-col">
          {/* Stream Info */}
          {stream && (
            <div className="bg-muted p-3 rounded-md">
              <p className="text-xs text-muted-foreground mb-1">Stream Name</p>
              <p className="font-medium text-sm truncate" title={stream.stream_name}>
                {stream.stream_name}
              </p>
              <div className="flex items-center gap-4 mt-1">
                {stream.group_name && (
                  <p className="text-xs text-muted-foreground">
                    Group: {stream.group_name}
                  </p>
                )}
                {stream.current_event_id && (
                  <Badge variant="warning" className="text-xs">
                    Currently matched (incorrect)
                  </Badge>
                )}
              </div>
            </div>
          )}

          {/* League and Date Selection */}
          <div className="flex gap-2">
            {leaguesLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading leagues...
              </div>
            ) : (
              <>
                <Select
                  className="flex-1"
                  value={league}
                  onChange={(e) => onLeagueChange(e.target.value)}
                >
                  <option value="">Select a league...</option>
                  {Object.entries(leaguesBySport).map(([sport, leagues]) => (
                    <optgroup key={sport} label={sport}>
                      {leagues.map((l) => (
                        <option key={l.slug} value={l.slug}>
                          {getLeagueDisplayName(l)}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </Select>
                <Input
                  type="text"
                  value={teamFilter}
                  onChange={(e) => onTeamFilterChange(e.target.value)}
                  placeholder="Filter by team..."
                  className="w-36"
                />
                <Input
                  type="date"
                  value={targetDate}
                  onChange={(e) => onTargetDateChange(e.target.value)}
                  className="w-40"
                  title="Target date for event search"
                />
                <Button
                  onClick={onSearch}
                  disabled={!league || loading}
                >
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                  Search
                </Button>
              </>
            )}
          </div>

          {/* Events List */}
          <div className="flex-1 overflow-auto border rounded-md">
            {events.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground text-sm">
                {loading ? "Searching..." : "Select a league and click Search"}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40%]">Matchup</TableHead>
                    <TableHead className="w-[25%]">Time</TableHead>
                    <TableHead className="w-[20%]">Status</TableHead>
                    <TableHead className="w-[15%]">Select</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <TableRow
                      key={event.event_id}
                      className={selectedEventId === event.event_id ? "bg-muted" : ""}
                    >
                      <TableCell className="font-medium">
                        {event.away_team && event.home_team ? (
                          <span>
                            {event.away_team} @ {event.home_team}
                          </span>
                        ) : (
                          event.event_name
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDateTime(event.start_time)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={event.status === "in" ? "default" : "secondary"}>
                          {event.status || "scheduled"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant={selectedEventId === event.event_id ? "default" : "outline"}
                          size="sm"
                          onClick={() => onSelectEvent(event.event_id)}
                        >
                          {selectedEventId === event.event_id ? <Check className="h-4 w-4" /> : "Select"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>

        <DialogFooter className="flex justify-between sm:justify-between mt-4">
          <Button
            variant="destructive"
            onClick={onSkip}
            disabled={submitting}
            title="Mark this stream to be skipped (no event match)"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <XCircle className="h-4 w-4 mr-2" />
            )}
            Skip Stream
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={onCorrect}
              disabled={!selectedEventId || submitting}
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Applying...
                </>
              ) : (
                "Apply Match"
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
