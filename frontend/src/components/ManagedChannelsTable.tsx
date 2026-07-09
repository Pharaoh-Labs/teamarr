import React, { useState, useMemo, useRef, useEffect, useCallback } from "react"
import { toast } from "sonner"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { StickyActionBar } from "@/components/ui/sticky-action-bar"
import { Spinner } from "@/components/ui/spinner"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Trash2,
  Loader2,
  Clock,
  Tv,
  Search,
  AlertTriangle,
  X,
  ChevronRight,
  ChevronDown,
  Info,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { FilterSelect } from "@/components/ui/filter-select"
import {
  useManagedChannels,
  useDeleteManagedChannel,
  usePendingDeletions,
} from "@/hooks/useChannels"
import { useGroups } from "@/hooks/useGroups"
import { useQuery } from "@tanstack/react-query"
import { getLeagues } from "@/api/teams"
import { deleteManagedChannel, getChannelStreams } from "@/api/channels"
import type { ManagedChannel, ChannelStreamEntry, StreamRuleMatch } from "@/api/channels"
import { OrphansDialog } from "@/components/managed-channels/OrphansDialog"
import { ResetAllDialog } from "@/components/managed-channels/ResetAllDialog"
import { getLeagueDisplayName, getSportDisplayName } from "@/lib/utils"
import { useSports } from "@/hooks/useSports"
import { useRowSelection } from "@/hooks/useRowSelection"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useGenerationProgress } from "@/hooks/useGenerationProgress"

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "-"
  const date = new Date(dateStr)
  return date.toLocaleString()
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "-"
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = date.getTime() - now.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)

  if (diffMs < 0) {
    const absMins = Math.abs(diffMins)
    const absHours = Math.abs(diffHours)
    if (absMins < 60) return `${absMins}m ago`
    if (absHours < 24) return `${absHours}h ago`
    return formatDateTime(dateStr)
  }

  if (diffMins < 60) return `in ${diffMins}m`
  if (diffHours < 24) return `in ${diffHours}h`
  return formatDateTime(dateStr)
}

function StreamStatsBadges({ stats }: { stats: Record<string, unknown> | null }) {
  if (!stats) return <span className="text-muted-foreground">—</span>

  const chip = (content: React.ReactNode) => (
    <span className="inline-flex rounded px-1.5 py-0.5 bg-muted text-[11px] font-mono leading-none text-muted-foreground">
      {content}
    </span>
  )

  const chips: React.ReactNode[] = []

  const resolution = stats.resolution as string | undefined
  if (resolution && resolution.includes("x")) {
    chips.push(chip(resolution.replace("x", "×")))
  }

  const fps = stats.source_fps as number | undefined
  if (fps != null) chips.push(chip(`${fps}fps`))

  const bitrate = stats.ffmpeg_output_bitrate as number | undefined
  if (bitrate != null) chips.push(chip(bitrate >= 1000 ? `${(bitrate / 1000).toFixed(1)} Mbps` : `${bitrate} kbps`))

  const audioBitrate = stats.audio_bitrate as number | undefined
  if (audioBitrate != null) chips.push(chip(`${audioBitrate} kbps audio`))

  const sampleRate = stats.sample_rate as number | undefined
  if (sampleRate != null) chips.push(chip(`${(sampleRate / 1000).toFixed(0)} kHz`))

  if (chips.length === 0) return <span className="text-muted-foreground">—</span>

  return <div className="flex flex-wrap gap-1 items-center">{chips.map((c, i) => <React.Fragment key={i}>{c}</React.Fragment>)}</div>
}

function getMatchMethodBadge(method: string | null) {
  if (!method) return null
  switch (method) {
    case "epg":
      return <Badge variant="info" className="text-xs">EPG</Badge>
    case "fuzzy":
      return <Badge variant="secondary" className="text-xs">Fuzzy</Badge>
    case "exact":
      return <Badge variant="outline" className="text-xs">Exact</Badge>
    default:
      return <Badge variant="outline" className="text-xs">{method}</Badge>
  }
}

const RULE_TYPE_LABELS: Record<string, string> = {
  m3u: "M3U Account",
  group: "Event Group",
  regex: "Regex",
  stream_type: "Stream Type",
  team_feed: "Home/Away Feed",
  not_team_feed: "Not Home/Away Feed",
  epg_match: "EPG Match",
  dispatcharr_group: "Dispatcharr Group",
  stats_metric: "Stats Metric",
  catch_all: "Everything else",
}

// Close a popover on outside-click / Escape. Shared by the click-popovers below
// (same behavior as StatsMetricBuilder's dropdown).
function useOutsideDismiss(
  ref: React.RefObject<HTMLElement | null>,
  open: boolean,
  setOpen: (v: boolean) => void,
) {
  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [ref, open, setOpen])
}

// Clickable priority number → compact popover explaining which ordering rules
// matched the stream, with the winning rule (the one that set the priority)
// highlighted.
function PriorityCell(
  { priority, rules, generating }: { priority: number; rules: StreamRuleMatch[]; generating: boolean },
) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useOutsideDismiss(ref, open, setOpen)

  // Nothing to explain and not generating → just the number.
  if (rules.length === 0 && !generating) {
    return <span className="text-muted-foreground">{priority}</span>
  }

  // Winners first, then by ascending rule priority.
  const ordered = [...rules].sort(
    (a, b) => Number(b.is_winner) - Number(a.is_winner) || a.priority - b.priority
  )

  // The popover evaluates the CURRENT rules; the stored number is from the last
  // generation run. If they disagree, the rules changed since this stream was
  // ordered and the stored order is stale until the next run. While a generation
  // is running the number is mid-update, so we show a spinner instead of flagging
  // it stale.
  const winner = ordered.find((r) => r.is_winner)
  const stale = !generating && winner != null && winner.priority !== priority

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`underline decoration-dotted underline-offset-2 ${
          stale
            ? "text-amber-500 decoration-amber-500 hover:text-amber-400"
            : "text-muted-foreground hover:text-foreground"
        }`}
        title={
          generating
            ? "Generation in progress — priority is updating"
            : stale
              ? "Rules changed since last sync — click for details"
              : "Show matched rules"
        }
      >
        {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <>{priority}{stale && "*"}</>}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-md border bg-popover p-1.5 shadow-lg">
          {rules.length > 0 && (
          <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
            Matched rules
          </div>
          )}
          <div className="space-y-0.5">
            {ordered.map((r, i) => (
              <div
                key={i}
                className={`flex items-start gap-1.5 rounded px-1 py-0.5 ${
                  r.is_winner ? "bg-primary/10" : ""
                } ${r.type === "catch_all" && !r.is_winner ? "opacity-50" : ""}`}
              >
                <span className="shrink-0 font-mono text-[11px] leading-5 tabular-nums text-muted-foreground">
                  {r.priority}
                </span>
                <span className="min-w-0 flex-1">
                  {/* Name shares a line with the number (and badge); subtitle drops below. */}
                  <span className="flex items-center gap-1.5">
                    <span className="text-[11px] font-medium leading-5 truncate">
                      {RULE_TYPE_LABELS[r.type] ?? r.type}
                    </span>
                    {r.is_winner && (
                      <Badge variant="info" className="shrink-0 text-[9px] px-1 py-0">applied</Badge>
                    )}
                  </span>
                  {r.value && (
                    <span className="block truncate font-mono text-[10px] text-muted-foreground" title={r.value}>
                      {r.value}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
          {generating ? (
            <div className={`text-[10px] leading-snug text-muted-foreground ${rules.length > 0 ? "mt-1 border-t pt-1" : ""}`}>
              Generation in progress — the order is updating.
            </div>
          ) : stale ? (
            <div className="mt-1 border-t pt-1 text-[10px] leading-snug text-amber-500">
              Rules changed since this stream was ordered (stored #{priority}). The order above
              applies on the next generation run.
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

const METHOD_INFO: Record<string, { label: string; desc: string }> = {
  epg: { label: "EPG", desc: "Matched via Dispatcharr's program guide (program title / sub-title)." },
  fuzzy: { label: "Fuzzy", desc: "Matched by fuzzy comparison of the stream name to the event." },
  exact: { label: "Exact", desc: "Exact name match." },
  cache: { label: "Cache", desc: "Reused a previously cached match for this stream." },
  alias: { label: "Alias", desc: "Matched via a user-defined team alias." },
  pattern: { label: "Pattern", desc: "Matched via a team-name pattern." },
  keyword: { label: "Keyword", desc: "Matched via an event keyword (e.g. UFC / boxing cards)." },
  user_corrected: { label: "Pinned", desc: "Manually corrected by you — pinned, never auto-rematched." },
  no_match: { label: "No match", desc: "No event matched this stream." },
}

// Clickable match-method badge → popover explaining how/why the stream matched
// its event. Combines fields always on the stream (method, type, exception
// keyword) with cache-derived detail (matched event, user correction) that's
// only present for fingerprint-cached matches.
function MethodCell({ stream }: { stream: ChannelStreamEntry }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useOutsideDismiss(ref, open, setOpen)

  const badge = getMatchMethodBadge(stream.match_method)
  if (!badge) return <span className="text-muted-foreground">—</span>

  const info = stream.match_method ? METHOD_INFO[stream.match_method] : undefined
  // The finer cache method only adds value when it differs from the badge method.
  const finer =
    stream.cache_match_method && stream.cache_match_method !== stream.match_method
      ? METHOD_INFO[stream.cache_match_method] ?? { label: stream.cache_match_method, desc: "" }
      : undefined

  return (
    <div className="relative inline-block" ref={ref}>
      <button onClick={() => setOpen((v) => !v)} title="Show match details" className="cursor-pointer">
        {badge}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-md border bg-popover p-2 shadow-lg space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
            Match details
          </div>
          <div>
            <span className="text-[11px] font-medium">{info?.label ?? stream.match_method}</span>
            {info?.desc && <p className="text-[10px] text-muted-foreground leading-snug">{info.desc}</p>}
          </div>
          {finer && (
            <div className="text-[10px] text-muted-foreground">
              Cache method: <span className="font-medium text-foreground">{finer.label}</span>
            </div>
          )}
          {stream.cache_created_at && (
            <div className="text-[10px] text-muted-foreground">
              Cached {formatRelativeTime(stream.cache_created_at)}
            </div>
          )}
          {[...stream.match_aliases, ...stream.match_patterns].length > 0 && (
            <div className="text-[10px] text-muted-foreground">
              {[...stream.match_aliases, ...stream.match_patterns].map((a, i) => (
                <div key={i} className="flex items-center gap-1">
                  <span className="font-mono text-foreground">{a.text}</span>
                  <span className="text-muted-foreground/60">→</span>
                  <span className="font-medium text-foreground truncate">{a.team}</span>
                </div>
              ))}
            </div>
          )}
          {stream.matched_event && (
            <div className="text-[10px] text-muted-foreground">
              Matched event:{" "}
              <span className="font-medium text-foreground">{stream.matched_event}</span>
              {stream.matched_league && <span className="uppercase"> ({stream.matched_league})</span>}
            </div>
          )}
          {stream.match_type && (
            <div className="text-[10px] text-muted-foreground">
              Type: <span className="font-medium text-foreground">{stream.match_type === "team" ? "Team" : "Event"}</span>
            </div>
          )}
          {stream.exception_keyword && (
            <div className="text-[10px] text-muted-foreground">
              Keyword: <span className="font-mono text-foreground">{stream.exception_keyword}</span>
            </div>
          )}
          {stream.user_corrected && (
            <div className="flex items-center gap-1.5">
              <Badge variant="info" className="text-[9px] px-1 py-0">pinned</Badge>
              <span className="text-[10px] text-muted-foreground">
                Corrected by you{stream.corrected_at ? ` ${formatRelativeTime(stream.corrected_at)}` : ""}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function getSyncStatusBadge(status: string) {
  switch (status) {
    case "in_sync":
      return <Badge variant="success">In Sync</Badge>
    case "pending":
      return <Badge variant="secondary">Pending</Badge>
    case "created":
      return <Badge variant="info">Created</Badge>
    case "drifted":
      return <Badge variant="warning">Drifted</Badge>
    case "orphaned":
      return <Badge variant="destructive">Orphaned</Badge>
    case "error":
      return <Badge variant="destructive">Error</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

interface ChannelRowProps {
  channel: ManagedChannel
  expanded: boolean
  selected: boolean
  streams: ChannelStreamEntry[] | undefined
  loading: boolean
  isGenerating: boolean
  sportLabel: string
  leagueLabel: string
  groupTitle: string | undefined
  onToggleExpand: (id: number) => void
  onToggleSelect: (id: number) => void
  onDelete: (channel: ManagedChannel) => void
}

// Memoized so per-row state changes (expand, select) don't re-render the whole
// table. All callbacks passed in are identity-stable.
const ChannelRow = React.memo(function ChannelRow({
  channel,
  expanded,
  selected,
  streams,
  loading,
  isGenerating,
  sportLabel,
  leagueLabel,
  groupTitle,
  onToggleExpand,
  onToggleSelect,
  onDelete,
}: ChannelRowProps) {
  return (
    <>
      <TableRow className={expanded ? "border-b-0" : ""}>
        <TableCell className="px-1">
          <button
            onClick={() => onToggleExpand(channel.id)}
            className="flex items-center justify-center w-6 h-6 text-muted-foreground hover:text-foreground"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded
              ? <ChevronDown className="h-4 w-4" />
              : <ChevronRight className="h-4 w-4" />}
          </button>
        </TableCell>
        <TableCell>
          <Checkbox
            checked={selected}
            onCheckedChange={() => onToggleSelect(channel.id)}
          />
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-2">
            {channel.logo_url && (
              <img
                src={channel.logo_url}
                alt=""
                className="h-6 w-6 object-contain"
              />
            )}
            <div>
              <div className="font-medium">{channel.channel_name}</div>
              <div className="text-xs text-muted-foreground">
                {channel.channel_number ? `#${channel.channel_number}` : ""}{" "}
                {channel.tvg_id}
              </div>
            </div>
          </div>
        </TableCell>
        <TableCell>
          <div className="max-w-xs">
            <div className="truncate text-sm">
              {channel.home_team || channel.away_team
                ? `${channel.away_team ?? ""} @ ${channel.home_team ?? ""}`
                : channel.event_name ?? "-"}
            </div>
            {channel.event_date && (
              <div className="text-xs text-muted-foreground">
                {new Date(channel.event_date).toLocaleString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </div>
            )}
          </div>
        </TableCell>
        <TableCell className="text-sm truncate" title={groupTitle}>
          {sportLabel}
        </TableCell>
        <TableCell>
          <Badge variant="secondary" className="text-xs">{leagueLabel}</Badge>
        </TableCell>
        <TableCell>{getSyncStatusBadge(channel.sync_status)}</TableCell>
        <TableCell className="text-muted-foreground">
          {formatRelativeTime(channel.scheduled_delete_at)}
        </TableCell>
        <TableCell>
          <div className="flex items-center justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(channel)}
              title="Delete"
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </TableCell>
        <TableCell></TableCell>
      </TableRow>
      {expanded && (
        <TableRow className="hover:bg-transparent border-b border-border/40">
          <TableCell colSpan={10} className="p-0 pb-2">
            <div className="ml-4 border-l-2 border-border/50 pl-2 pr-4 pt-2">
            {loading ? (
              <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading streams…
              </div>
            ) : (streams ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground py-1">No active streams.</p>
            ) : (
              <table className="w-full text-xs">
                <colgroup>
                  <col className="w-[28%]" />
                  <col className="w-[18%]" />
                  <col className="w-[16%]" />
                  <col className="w-[10%]" />
                  <col className="w-[6%]" />
                  <col className="w-[22%]" />
                </colgroup>
                <thead>
                  <tr>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5 pr-4">Stream</th>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5 pr-4">Group</th>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5 pr-4">Account</th>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5 pr-4">Method</th>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5 pr-2">Sort</th>
                    <th className="text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 pb-1.5">
                      <span className="inline-flex items-center gap-1">
                        Stats
                        <RichTooltip
                          content="External stream stats (resolution, bitrate, fps, etc.) populated by Dispatcharr's stream probe. Only present once Dispatcharr has probed the stream."
                          side="top"
                        >
                          <Info className="h-3 w-3 text-muted-foreground/50 cursor-help shrink-0" />
                        </RichTooltip>
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(streams ?? []).map((stream) => (
                    <tr key={stream.dispatcharr_stream_id} className="border-t border-border/30">
                      <td className="py-1 pr-4 font-medium">{stream.stream_name ?? `#${stream.dispatcharr_stream_id}`}</td>
                      <td className="py-1 pr-4 text-muted-foreground">{stream.source_group ?? "—"}</td>
                      <td className="py-1 pr-4 text-muted-foreground">{stream.m3u_account_name ?? "—"}</td>
                      <td className="py-1 pr-4"><MethodCell stream={stream} /></td>
                      <td className="py-1 pr-4"><PriorityCell priority={stream.priority} rules={stream.matched_rules} generating={isGenerating} /></td>
                      <td className="py-1"><StreamStatsBadges stats={stream.stream_stats} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
})

export function ManagedChannelsTable() {
  // Filter states
  const [nameFilter, setNameFilter] = useState<string>("")
  const [sportFilter, setSportFilter] = useState<string>("")
  const [leagueFilter, setLeagueFilter] = useState<string>("")
  const [statusFilter, setStatusFilter] = useState<string>("")

  // Expand states
  const [expandedChannels, setExpandedChannels] = useState<Set<number>>(new Set())
  const [channelStreams, setChannelStreams] = useState<Map<number, ChannelStreamEntry[]>>(new Map())
  const [loadingStreams, setLoadingStreams] = useState<Set<number>>(new Set())

  const { isGenerating } = useGenerationProgress()

  // UI states
  const [deleteConfirm, setDeleteConfirm] = useState<ManagedChannel | null>(null)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)
  const [orphansModalOpen, setOrphansModalOpen] = useState(false)
  const [resetModalOpen, setResetModalOpen] = useState(false)

  const queryClient = useQueryClient()

  const { data: groups } = useGroups()
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports ?? {}
  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
    staleTime: 1000 * 60 * 60, // 1 hour
  })
  const {
    data: channelsData,
    isLoading,
    error,
    refetch,
  } = useManagedChannels(undefined, false)
  const { data: pendingData } = usePendingDeletions()

  // Fetch all channels including deleted for the Recently Deleted section.
  // No polling: mutations invalidate ["managedChannels"] so this refreshes on
  // deletions without a second full-table 30s poll.
  const { data: allChannelsData } = useManagedChannels(undefined, true, { poll: false })

  // Filter to get only deleted channels (last 50, sorted by deletion time)
  const deletedChannels = useMemo(() => {
    if (!allChannelsData?.channels) return []
    return allChannelsData.channels
      .filter((ch) => ch.deleted_at !== null)
      .sort((a, b) => {
        const dateA = new Date(a.deleted_at!).getTime()
        const dateB = new Date(b.deleted_at!).getTime()
        return dateB - dateA // Most recent first
      })
      .slice(0, 50)
  }, [allChannelsData])

  const deleteMutation = useDeleteManagedChannel()

  // Extract unique filter values from data
  const { sports, leagues, statuses } = useMemo(() => {
    const channels = channelsData?.channels ?? []
    const sportSet = new Set<string>()
    const leagueSet = new Set<string>()
    const statusSet = new Set<string>()
    for (const ch of channels) {
      if (ch.sport) sportSet.add(ch.sport)
      if (ch.league) leagueSet.add(ch.league)
      if (ch.sync_status) statusSet.add(ch.sync_status)
    }
    return {
      sports: Array.from(sportSet).sort(),
      leagues: Array.from(leagueSet).sort(),
      statuses: Array.from(statusSet).sort(),
    }
  }, [channelsData])

  // Group ID -> name lookup
  const groupLookup = useMemo(() => {
    const map = new Map<number, string>()
    for (const g of groups?.groups ?? []) {
      map.set(g.id, g.name)
    }
    return map
  }, [groups])

  // League slug -> display name lookup (uses {league} variable resolution: alias first, then name)
  const getLeagueDisplay = useMemo(() => {
    const map = new Map<string, string>()
    for (const league of leaguesData?.leagues ?? []) {
      // {league} variable uses league_alias if available, otherwise display_name (name field)
      map.set(league.slug, getLeagueDisplayName(league, true))
    }
    return (slug: string | null | undefined) => {
      if (!slug) return "-"
      return map.get(slug) ?? slug.toUpperCase()
    }
  }, [leaguesData])

  // Apply client-side filters
  const filteredChannels = useMemo(() => {
    let channels = channelsData?.channels ?? []
    if (nameFilter) {
      const searchLower = nameFilter.toLowerCase()
      channels = channels.filter((ch) =>
        ch.channel_name.toLowerCase().includes(searchLower)
      )
    }
    if (sportFilter) {
      channels = channels.filter((ch) => ch.sport === sportFilter)
    }
    if (leagueFilter) {
      channels = channels.filter((ch) => ch.league === leagueFilter)
    }
    if (statusFilter) {
      channels = channels.filter((ch) => ch.sync_status === statusFilter)
    }
    return channels
  }, [channelsData, nameFilter, sportFilter, leagueFilter, statusFilter])

  const {
    selectedIds,
    toggle: toggleSelect,
    toggleAll: toggleSelectAll,
    isAllSelected,
    setSelectedIds,
  } = useRowSelection(filteredChannels)

  // Mutation for bulk delete
  const bulkDeleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      const results = await Promise.allSettled(
        ids.map((id) => deleteManagedChannel(id))
      )
      const succeeded = results.filter((r) => r.status === "fulfilled").length
      const failed = results.filter((r) => r.status === "rejected").length
      return { succeeded, failed }
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["managed-channels"] })
      refetch()
      toast.success(`Deleted ${result.succeeded} channel(s)${result.failed > 0 ? `, ${result.failed} failed` : ""}`)
      setSelectedIds(new Set())
      setBulkDeleteConfirm(false)
    },
    onError: () => {
      toast.error("Bulk delete failed")
    },
  })

  // Fetch (or refetch) the stream detail for one channel into local state.
  const fetchStreams = useCallback(async (channelId: number) => {
    setLoadingStreams((prev) => new Set(prev).add(channelId))
    try {
      const data = await getChannelStreams(channelId)
      setChannelStreams((prev) => new Map(prev).set(channelId, data.streams))
    } catch {
      setChannelStreams((prev) => new Map(prev).set(channelId, []))
    } finally {
      setLoadingStreams((prev) => { const s = new Set(prev); s.delete(channelId); return s })
    }
  }, [])

  // Refs so handleToggleExpand can stay identity-stable for the memo'd rows.
  const channelStreamsRef = useRef(channelStreams)
  channelStreamsRef.current = channelStreams
  const expandedRef = useRef(expandedChannels)
  expandedRef.current = expandedChannels

  const handleToggleExpand = useCallback((channelId: number) => {
    setExpandedChannels((prev) => {
      const next = new Set(prev)
      if (next.has(channelId)) {
        next.delete(channelId)
      } else {
        next.add(channelId)
      }
      return next
    })
    // Opening (wasn't expanded before) with no cached detail → fetch.
    if (!expandedRef.current.has(channelId) && !channelStreamsRef.current.has(channelId)) {
      fetchStreams(channelId)
    }
  }, [fetchStreams])

  // When a generation run finishes, stream priorities/membership may have
  // changed. Refresh the channels list and any expanded stream tables so the
  // priority spinners resolve to the new ordering.
  const wasGeneratingRef = useRef(isGenerating)
  useEffect(() => {
    if (wasGeneratingRef.current && !isGenerating) {
      queryClient.invalidateQueries({ queryKey: ["managedChannels"] })
      expandedRef.current.forEach((id) => { void fetchStreams(id) })
    }
    wasGeneratingRef.current = isGenerating
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGenerating])

  const handleDelete = async () => {
    if (!deleteConfirm) return
    try {
      const result = await deleteMutation.mutateAsync(deleteConfirm.id)
      if (result.success) {
        toast.success(result.message)
      } else {
        toast.error(result.message)
      }
      setDeleteConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete channel")
    }
  }

  const handleBulkDelete = () => {
    bulkDeleteMutation.mutate(Array.from(selectedIds))
  }

  if (error) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-bold">Managed Channels</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">Error loading channels: {error.message}</p>
            <Button className="mt-4" onClick={() => refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <CollapsibleSection
        title="Managed Channels"
        icon={<Tv className="h-5 w-5 text-muted-foreground" />}
        count={
          filteredChannels.length !== (channelsData?.channels.length ?? 0)
            ? `(${filteredChannels.length} of ${channelsData?.channels.length ?? 0})`
            : `(${channelsData?.channels.length ?? 0})`
        }
        persistKey="channels.active"
      >

      {/* Section actions — live inside the collapsible body so they only show
          when the section is expanded. */}
      <div className="flex justify-end gap-2 mb-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setOrphansModalOpen(true)}
        >
          <Search className="h-4 w-4 mr-1" />
          Find Orphans
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => setResetModalOpen(true)}
        >
          <AlertTriangle className="h-4 w-4 mr-1" />
          Reset All
        </Button>
      </div>

      {/* Fixed Batch Operations Bar */}
      {selectedIds.size > 0 && (
        <StickyActionBar
          label={
            <>
                {selectedIds.size} channel{selectedIds.size > 1 ? "s" : ""} selected
            </>
          }
        >
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedIds(new Set())}
                >
                  Clear Selection
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setBulkDeleteConfirm(true)}
                >
                  <Trash2 className="h-4 w-4 mr-1" />
                  Delete Selected
                </Button>
        </StickyActionBar>
      )}

      {/* Pending Deletions Info */}
      {pendingData && pendingData.count > 0 && (
        <Card className="bg-muted/50">
          <CardContent className="py-3">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm">
                <strong>{pendingData.count}</strong> channel{pendingData.count > 1 ? "s" : ""} pending deletion
                {pendingData.channels[0] && (
                  <span className="text-muted-foreground">
                    {" "}— Next: {pendingData.channels[0].channel_name}
                  </span>
                )}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Channels List */}
          {isLoading ? (
            <Spinner />
          ) : (channelsData?.channels.length ?? 0) === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No managed channels found.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8"></TableHead>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={isAllSelected}
                      onCheckedChange={toggleSelectAll}
                    />
                  </TableHead>
                  <TableHead className="w-[25%]">Channel</TableHead>
                  <TableHead className="w-[25%]">Event</TableHead>
                  <TableHead className="w-28">Sport</TableHead>
                  <TableHead className="w-20">League</TableHead>
                  <TableHead className="w-20">Status</TableHead>
                  <TableHead className="w-24">Delete At</TableHead>
                  <TableHead className="w-16 text-right">Actions</TableHead>
                  <TableHead className="w-6"></TableHead>
                </TableRow>
                {/* Filter row */}
                <TableRow className="border-b-2 border-border">
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <div className="relative">
                      <Input
                        type="text"
                        placeholder="Filter..."
                        value={nameFilter}
                        onChange={(e) => setNameFilter(e.target.value)}
                        className="h-[18px] text-[0.65rem] italic px-1 pr-4 rounded-sm"
                      />
                      {nameFilter && (
                        <button
                          onClick={() => setNameFilter("")}
                          className="absolute right-0.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                      )}
                    </div>
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect
                      value={sportFilter}
                      onChange={setSportFilter}
                      options={[
                        { value: "", label: "All" },
                        ...sports.map((s) => ({
                          value: s,
                          label: getSportDisplayName(s, sportsMap),
                        })),
                      ]}
                    />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect
                      value={leagueFilter}
                      onChange={setLeagueFilter}
                      options={[
                        { value: "", label: "All" },
                        ...leagues.map((l) => ({ value: l, label: l })),
                      ]}
                    />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect
                      value={statusFilter}
                      onChange={setStatusFilter}
                      options={[
                        { value: "", label: "All" },
                        ...statuses.map((s) => ({ value: s, label: s })),
                      ]}
                    />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredChannels.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center py-8 text-muted-foreground">
                      No channels match the current filters.
                    </TableCell>
                  </TableRow>
                ) : filteredChannels.map((channel) => (
                  <ChannelRow
                    key={channel.id}
                    channel={channel}
                    expanded={expandedChannels.has(channel.id)}
                    selected={selectedIds.has(channel.id)}
                    streams={channelStreams.get(channel.id)}
                    loading={loadingStreams.has(channel.id)}
                    isGenerating={isGenerating}
                    sportLabel={channel.sport ? getSportDisplayName(channel.sport, sportsMap) : "-"}
                    leagueLabel={getLeagueDisplay(channel.league)}
                    groupTitle={channel.event_epg_group_id ? groupLookup.get(channel.event_epg_group_id) : undefined}
                    onToggleExpand={handleToggleExpand}
                    onToggleSelect={toggleSelect}
                    onDelete={setDeleteConfirm}
                  />
                ))}
              </TableBody>
            </Table>
          )}

      </CollapsibleSection>

      {/* Recently Deleted */}
      {deletedChannels.length > 0 && (
        <CollapsibleSection
          title="Recently Deleted"
          icon={<Clock className="h-4 w-4 text-muted-foreground" />}
          count={`(${deletedChannels.length})`}
          persistKey="channels.deleted"
        >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Sport</TableHead>
                  <TableHead>League</TableHead>
                  <TableHead>Deleted</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {deletedChannels.map((channel) => (
                  <TableRow key={channel.id} className="text-muted-foreground">
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {channel.logo_url && (
                          <img
                            src={channel.logo_url}
                            alt=""
                            className="h-6 w-6 object-contain opacity-50"
                          />
                        )}
                        <div>
                          <div className="font-medium">{channel.channel_name}</div>
                          <div className="text-xs">{channel.tvg_id}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-xs truncate text-sm">
                        {channel.home_team || channel.away_team
                          ? `${channel.away_team ?? ""} @ ${channel.home_team ?? ""}`
                          : channel.event_name ?? "-"}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      {channel.sport ? getSportDisplayName(channel.sport, sportsMap) : "-"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">{getLeagueDisplay(channel.league)}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {channel.deleted_at
                        ? new Date(channel.deleted_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
        </CollapsibleSection>
      )}

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        title="Delete Channel"
        description={`Are you sure you want to delete "${deleteConfirm?.channel_name}"? This will also remove it from Dispatcharr if configured.`}
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
      />

      {/* Bulk Delete Confirmation */}
      <ConfirmDialog
        open={bulkDeleteConfirm}
        onOpenChange={setBulkDeleteConfirm}
        title={`Delete ${selectedIds.size} Channels`}
        description={`Are you sure you want to delete ${selectedIds.size} channel${selectedIds.size > 1 ? "s" : ""}? This will also remove them from Dispatcharr if configured.`}
        confirmLabel="Delete All"
        isPending={bulkDeleteMutation.isPending}
        onConfirm={handleBulkDelete}
      />

      {/* Find Orphans Modal */}
      <OrphansDialog open={orphansModalOpen} onOpenChange={setOrphansModalOpen} />

      {/* Reset All Modal */}
      <ResetAllDialog
        open={resetModalOpen}
        onOpenChange={setResetModalOpen}
        onReset={() => {
          refetch()
          queryClient.invalidateQueries({ queryKey: ["reconciliation"] })
        }}
      />
    </div>
  )
}
