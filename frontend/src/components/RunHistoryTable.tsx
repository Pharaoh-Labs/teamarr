import { useState, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  CheckCircle,
  XCircle,
  Ban,
  Loader2,
  Clock,
  Search,
  AlertTriangle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { ResponsiveTable, type ResponsiveColumn } from "@/components/ui/responsive-table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import { VirtualizedTable } from "@/components/VirtualizedTable"
import { useDateFormat } from "@/hooks/useDateFormat"
import { getMatchedStreams, getFailedMatches } from "@/api/epg"
import { getLeagues } from "@/api/teams"
import { getLeagueDisplayName } from "@/lib/utils"
import type { ProcessingRun, MatchedStream, FailedMatch } from "@/api/epg"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(ms: number | null): string {
  if (!ms) return "-"
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}

function formatBytes(bytes: number | undefined | null): string {
  if (bytes == null || isNaN(bytes) || bytes === 0) return "0 B"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Calls-per-channel is the call-volume regression signal (the #254 refetch bug
// ran ~16/ch; healthy warm runs are ~2, cold-cache runs ~5). Stay calm/muted in
// the normal band so the column only lights up when something is off.
function callsPerChannelClass(ratio: number): string {
  if (ratio >= 12) return "text-red-600 font-medium"
  if (ratio >= 6) return "text-amber-600"
  return "text-muted-foreground"
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-green-600" />
    case "failed":
      return <XCircle className="h-4 w-4 text-red-600" />
    case "cancelled":
      return <Ban className="h-4 w-4 text-orange-500" />
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
    default:
      return <Clock className="h-4 w-4 text-muted-foreground" />
  }
}

function getFailedReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    teams_not_parsed: "Could not parse teams",
    team1_not_found: "Team 1 not found",
    team2_not_found: "Team 2 not found",
    both_teams_not_found: "Neither team found",
    no_common_league: "No common league",
    no_league_detected: "No league detected",
    ambiguous_league: "Ambiguous league",
    no_event_found: "No event found",
    no_event_card_match: "No event card match",
    no_racing_match: "No racing match",
    no_tennis_match: "No tennis match",
    date_mismatch: "Date mismatch",
    unmatched: "Unmatched",
  }
  return labels[reason] || reason
}

function getMatchMethodBadge(method: string | null) {
  switch (method) {
    case "cache":
      return <Badge variant="secondary">Cache</Badge>
    case "user_corrected":
      return <Badge variant="success">User Fixed</Badge>
    case "alias":
      return <Badge variant="info">Alias</Badge>
    case "pattern":
      return <Badge variant="outline">Pattern</Badge>
    case "fuzzy":
      return <Badge variant="warning">Fuzzy</Badge>
    case "keyword":
      return <Badge variant="secondary">Keyword</Badge>
    case "direct":
      return <Badge variant="success">Direct</Badge>
    default:
      return <Badge variant="outline">{method ?? "Unknown"}</Badge>
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RunHistoryTableProps {
  runs: ProcessingRun[]
  /** Called when user clicks Fix on a matched or failed stream. Omit to hide Fix column. */
  onFixStream?: (stream: FailedMatch | MatchedStream) => void
}

export function RunHistoryTable({ runs, onFixStream }: RunHistoryTableProps) {
  const { formatDateTime } = useDateFormat()

  // Modal state
  const [matchedModalRunId, setMatchedModalRunId] = useState<number | null>(null)
  const [failedModalRunId, setFailedModalRunId] = useState<number | null>(null)

  // Filter state
  const [matchedFilter, setMatchedFilter] = useState("")
  const [matchedGroupFilter, setMatchedGroupFilter] = useState("all")
  const [failedFilter, setFailedFilter] = useState("")
  const [failedGroupFilter, setFailedGroupFilter] = useState("all")

  const anyModalOpen = matchedModalRunId !== null || failedModalRunId !== null

  // Queries — only fire when a modal is open
  const { data: matchedData, isLoading: matchedLoading } = useQuery({
    queryKey: ["matched-streams", matchedModalRunId],
    queryFn: () => getMatchedStreams(matchedModalRunId ?? undefined, undefined, 5000),
    enabled: matchedModalRunId !== null,
  })

  const { data: failedData, isLoading: failedLoading } = useQuery({
    queryKey: ["failed-matches", failedModalRunId],
    queryFn: () => getFailedMatches(failedModalRunId ?? undefined, undefined, undefined, 5000),
    enabled: failedModalRunId !== null,
  })

  const { data: leaguesData } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(false),
    enabled: anyModalOpen,
    staleTime: 5 * 60 * 1000,
  })

  const leagues = leaguesData?.leagues
  const matchedStreams = matchedData?.streams
  const failedFailures = failedData?.failures

  // League display lookup
  const getLeagueDisplay = useMemo(() => {
    const map = new Map<string, string>()
    if (leagues) {
      for (const league of leagues) {
        map.set(league.slug, getLeagueDisplayName(league, true))
      }
    }
    return (code: string | null) => (code ? (map.get(code) ?? code) : "-")
  }, [leagues])

  // Group dropdowns
  const matchedGroups = useMemo(() => {
    if (!matchedStreams) return []
    const groups = new Set<string>()
    for (const s of matchedStreams) if (s.group_name) groups.add(s.group_name)
    return Array.from(groups).sort()
  }, [matchedStreams])

  const failedGroups = useMemo(() => {
    if (!failedFailures) return []
    const groups = new Set<string>()
    for (const f of failedFailures) if (f.group_name) groups.add(f.group_name)
    return Array.from(groups).sort()
  }, [failedFailures])

  // Filtered data
  const filteredMatchedStreams = useMemo(() => {
    if (!matchedStreams) return []
    const q = matchedFilter.toLowerCase()
    return matchedStreams.filter((s) => {
      if (matchedGroupFilter !== "all" && s.group_name !== matchedGroupFilter) return false
      if (!q) return true
      return (
        s.stream_name.toLowerCase().includes(q) ||
        s.event_name?.toLowerCase().includes(q) ||
        s.home_team?.toLowerCase().includes(q) ||
        s.away_team?.toLowerCase().includes(q) ||
        s.league?.toLowerCase().includes(q)
      )
    })
  }, [matchedStreams, matchedFilter, matchedGroupFilter])

  const filteredFailedMatches = useMemo(() => {
    if (!failedFailures) return []
    const q = failedFilter.toLowerCase()
    return failedFailures.filter((f) => {
      if (failedGroupFilter !== "all" && f.group_name !== failedGroupFilter) return false
      if (!q) return true
      return (
        f.stream_name.toLowerCase().includes(q) ||
        f.parsed_team1?.toLowerCase().includes(q) ||
        f.parsed_team2?.toLowerCase().includes(q) ||
        f.detected_league?.toLowerCase().includes(q) ||
        f.reason.toLowerCase().includes(q)
      )
    })
  }, [failedFailures, failedFilter, failedGroupFilter])

  const closeMatchedModal = () => {
    setMatchedModalRunId(null)
    setMatchedFilter("")
    setMatchedGroupFilter("all")
  }

  const closeFailedModal = () => {
    setFailedModalRunId(null)
    setFailedFilter("")
    setFailedGroupFilter("all")
  }

  // One column config drives both the desktop table and the mobile cards.
  const columns: ResponsiveColumn<ProcessingRun>[] = [
    {
      key: "status",
      header: "Status",
      headerClassName: "w-10",
      mobileTitle: true,
      cell: (run) => <StatusIcon status={run.status} />,
    },
    {
      key: "time",
      header: "Time",
      mobileTitle: true,
      cell: (run) => <span className="text-muted-foreground">{formatDateTime(run.started_at)}</span>,
    },
    {
      key: "processed",
      header: "Processed",
      align: "center",
      cell: (run) => {
        const teams = (run.extra_metrics?.teams_processed as number) ?? 0
        const groups = (run.extra_metrics?.groups_processed as number) ?? 0
        return (
          <span className="text-muted-foreground text-xs">
            {teams} Teams / {groups} Event Groups
          </span>
        )
      },
    },
    {
      key: "programmes",
      header: "Programmes",
      align: "center",
      cell: (run) => (
        <RichTooltip
          title="Breakdown"
          rows={[
            { label: "Events", value: run.programmes?.events ?? 0 },
            { label: "Pregame", value: run.programmes?.pregame ?? 0 },
            { label: "Postgame", value: run.programmes?.postgame ?? 0 },
            { label: "Idle", value: run.programmes?.idle ?? 0 },
          ]}
        >
          <span className="cursor-help tabular-nums">{run.programmes?.total ?? 0}</span>
        </RichTooltip>
      ),
    },
    {
      key: "matched",
      header: "Matched",
      align: "center",
      cell: (run) => (
        <button
          className="cursor-pointer text-green-600 hover:underline font-medium tabular-nums"
          onClick={() => setMatchedModalRunId(run.id)}
        >
          {run.streams?.matched ?? 0}
        </button>
      ),
    },
    {
      key: "failed",
      header: "Failed",
      align: "center",
      cell: (run) => (
        <button
          className="cursor-pointer text-red-600 hover:underline font-medium tabular-nums"
          onClick={() => setFailedModalRunId(run.id)}
        >
          {run.streams?.unmatched ?? 0}
        </button>
      ),
    },
    {
      key: "channels",
      header: "Channels",
      align: "center",
      cell: (run) => <span className="tabular-nums">{run.channels?.active ?? 0}</span>,
    },
    {
      key: "api_calls",
      header: "API Calls",
      align: "center",
      cell: (run) => {
        const total = run.extra_metrics?.provider_calls_total as number | undefined
        // Runs before kbbk.2 have no telemetry — show a dash, not a fake 0.
        if (total == null) return <span className="text-muted-foreground">—</span>
        const calls = (run.extra_metrics?.provider_calls as Record<string, number>) ?? {}
        const channels = run.channels?.active ?? 0
        const ratio = channels > 0 ? total / channels : total
        const rows = [
          ...Object.entries(calls).map(([label, value]) => ({ label, value })),
          { label: "Total", value: total },
        ]
        return (
          <RichTooltip title="Provider calls" rows={rows}>
            <span className={`cursor-help tabular-nums ${callsPerChannelClass(ratio)}`}>
              {ratio.toFixed(1)}/ch
            </span>
          </RichTooltip>
        )
      },
    },
    {
      key: "duration",
      header: "Duration",
      cell: (run) => formatDuration(run.duration_ms),
    },
    {
      key: "size",
      header: "Size",
      cell: (run) => (
        <span className="text-muted-foreground">{formatBytes(run.xmltv_size_bytes)}</span>
      ),
    },
  ]

  return (
    <>
      <ResponsiveTable rows={runs} columns={columns} keyExtractor={(run) => run.id} />

      {/* Matched Streams Modal */}
      <Dialog open={matchedModalRunId !== null} onOpenChange={(open) => { if (!open) closeMatchedModal() }}>
        <DialogContent onClose={closeMatchedModal} className="max-w-6xl h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-green-600" />
              Matched Streams
            </DialogTitle>
            <DialogDescription>
              Streams successfully matched to events (Run #{matchedModalRunId})
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-3 pb-2 border-b">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search streams, events, teams..."
                value={matchedFilter}
                onChange={(e) => setMatchedFilter(e.target.value)}
                className="pl-9 h-9"
              />
            </div>
            <select
              value={matchedGroupFilter}
              onChange={(e) => setMatchedGroupFilter(e.target.value)}
              className="h-9 px-3 rounded-md border border-input bg-background text-sm"
            >
              <option value="all">All Groups</option>
              {matchedGroups.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          {matchedLoading ? (
            <div className="flex-1 flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredMatchedStreams.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              {(matchedData?.streams.length ?? 0) === 0
                ? "No matched streams for this run."
                : "No streams match your filter."}
            </div>
          ) : (
            <VirtualizedTable<MatchedStream>
              data={filteredMatchedStreams}
              getRowKey={(item) => item.id}
              rowHeight={56}
              columns={[
                {
                  header: "Stream Name",
                  width: "flex-1 min-w-0",
                  render: (stream) => (
                    <span className="font-medium truncate block" title={stream.stream_name}>
                      {stream.stream_name}
                    </span>
                  ),
                },
                {
                  header: "Event",
                  width: "w-56",
                  render: (stream) => (
                    <div>
                      <div className="truncate" title={stream.event_name || `${stream.away_team} @ ${stream.home_team}`}>
                        {stream.event_name || `${stream.away_team} @ ${stream.home_team}`}
                      </div>
                      {stream.event_date && (
                        <div className="text-xs text-muted-foreground">
                          {new Date(stream.event_date).toLocaleDateString()}
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  header: "League",
                  width: "w-20",
                  render: (stream) => (
                    <Badge variant="secondary">{getLeagueDisplay(stream.league)}</Badge>
                  ),
                },
                {
                  header: "Method",
                  width: "w-28",
                  render: (stream) => (
                    <div>
                      {getMatchMethodBadge(stream.match_method)}
                      {!!stream.from_cache && stream.match_method !== "cache" && (
                        <Badge variant="outline" className="ml-1">Cached</Badge>
                      )}
                    </div>
                  ),
                },
                {
                  header: "Group",
                  width: "w-40",
                  render: (stream) => (
                    <span className="text-muted-foreground text-sm truncate block" title={stream.group_name ?? undefined}>
                      {stream.group_name}
                    </span>
                  ),
                },
                ...(onFixStream
                  ? [{
                      header: "Fix",
                      width: "w-12",
                      render: (stream: MatchedStream) => (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onFixStream(stream)}
                          title="Correct this match"
                        >
                          <AlertTriangle className="h-4 w-4" />
                        </Button>
                      ),
                    }]
                  : []),
              ]}
            />
          )}

          <DialogFooter>
            <div className="text-sm text-muted-foreground">
              {filteredMatchedStreams.length === (matchedData?.streams.length ?? 0)
                ? `${matchedData?.count ?? 0} matched streams`
                : `${filteredMatchedStreams.length} of ${matchedData?.count ?? 0} streams`}
            </div>
            <Button variant="outline" onClick={closeMatchedModal}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Failed Matches Modal */}
      <Dialog open={failedModalRunId !== null} onOpenChange={(open) => { if (!open) closeFailedModal() }}>
        <DialogContent onClose={closeFailedModal} className="max-w-6xl h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <XCircle className="h-5 w-5 text-red-600" />
              Failed Matches
            </DialogTitle>
            <DialogDescription>
              Streams that failed to match to events (Run #{failedModalRunId})
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-3 pb-2 border-b">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search streams, teams, reasons..."
                value={failedFilter}
                onChange={(e) => setFailedFilter(e.target.value)}
                className="pl-9 h-9"
              />
            </div>
            <select
              value={failedGroupFilter}
              onChange={(e) => setFailedGroupFilter(e.target.value)}
              className="h-9 px-3 rounded-md border border-input bg-background text-sm"
            >
              <option value="all">All Groups</option>
              {failedGroups.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          {failedLoading ? (
            <div className="flex-1 flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredFailedMatches.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              {(failedData?.failures.length ?? 0) === 0
                ? "No failed matches for this run."
                : "No streams match your filter."}
            </div>
          ) : (
            <VirtualizedTable<FailedMatch>
              data={filteredFailedMatches}
              getRowKey={(item) => item.id}
              rowHeight={56}
              columns={[
                {
                  header: "Stream Name",
                  width: "flex-1 min-w-0",
                  render: (failure) => (
                    <span className="font-medium truncate block" title={failure.stream_name}>
                      {failure.stream_name}
                    </span>
                  ),
                },
                {
                  header: "Reason",
                  width: "w-44",
                  render: (failure) => (
                    <span className="text-sm">{getFailedReasonLabel(failure.reason)}</span>
                  ),
                },
                {
                  header: "Group",
                  width: "w-48",
                  render: (failure) => (
                    <span className="text-muted-foreground text-sm truncate block" title={failure.group_name ?? undefined}>
                      {failure.group_name}
                    </span>
                  ),
                },
                ...(onFixStream
                  ? [{
                      header: "Fix",
                      width: "w-12",
                      render: (failure: FailedMatch) => (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onFixStream(failure)}
                          title="Fix this stream's match"
                        >
                          <AlertTriangle className="h-4 w-4" />
                        </Button>
                      ),
                    }]
                  : []),
              ]}
            />
          )}

          <DialogFooter>
            <div className="text-sm text-muted-foreground">
              {filteredFailedMatches.length === (failedData?.failures.length ?? 0)
                ? `${failedData?.count ?? 0} failed matches`
                : `${filteredFailedMatches.length} of ${failedData?.count ?? 0} matches`}
            </div>
            <Button variant="outline" onClick={closeFailedModal}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
