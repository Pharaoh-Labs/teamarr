import React, { useState, useMemo } from "react"
import { useNavigate } from "react-router"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import {
  Search,
  Trash2,
  Pencil,
  LoaderCircle,
  Plus,
  X,
  Check,
  CircleAlert,
  GripVertical,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Folder,
} from "lucide-react"
import { Alert } from "@/components/ui/alert"
import { StickyActionBar } from "@/components/ui/sticky-action-bar"
import { Spinner } from "@/components/ui/spinner"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import { Checkbox } from "@/components/ui/checkbox"
import { Switch } from "@/components/ui/switch"
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
import { FilterSelect } from "@/components/ui/filter-select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { usePersistentState } from "@/hooks/usePersistentState"
import { useTableSort } from "@/hooks/useTableSort"
import { useRowSelection } from "@/hooks/useRowSelection"
import { Input } from "@/components/ui/input"
import {
  useClearGroupMatchCache,
  useClearGroupsMatchCache,
  useGroups,
  useDeleteGroup,
  useToggleGroup,
  usePreviewGroup,
} from "@/hooks/useGroups"
import { useMatchRate, matchRateColor } from "@/hooks/useMatchRate"
import type { EventGroup, PreviewGroupResponse, SourceFolder } from "@/api/types"
import type { SourcePlacement } from "@/api/sourceFolders"
import {
  useDeleteSourceFolder,
  usePutArrangement,
  useSourceFolders,
  useUpdateSourceFolder,
} from "@/hooks/useSourceFolders"
import { LeagueChips } from "@/components/sources/LeagueChips"
import { ArrangeMenu } from "@/components/sources/ArrangeMenu"
import {
  getStaleGroups,
} from "@/api/groups"
import { useDateFormat } from "@/hooks/useDateFormat"
import { getLeagues } from "@/api/teams"
import { BulkEditDialog } from "./event-groups/BulkEditDialog"
import { SourceAutomation } from "@/components/SourceAutomation"
import { getFailedReasonLabel, getLeagueDisplayName } from "@/lib/utils"

// Helper to get display name (prefer display_name over name)
const getDisplayName = (group: EventGroup) => group.display_name || group.name

// Provider as the Provider column shows it: the M3U account, or Dispatcharr
// for a channel source. The filter keys on the same string.
const providerLabel = (group: EventGroup) =>
  group.m3u_account_name || (group.is_channel_source ? "Dispatcharr" : "")

// Top league by last-run share; a source with no matches sorts last.
const topLeague = (group: EventGroup) => group.league_shares?.[0]?.display_name ?? "\uffff"

type SortColumn = "name" | "provider" | "league" | "matched" | "status"

const SORT_COMPARATORS = {
  name: (a: EventGroup, b: EventGroup) => getDisplayName(a).localeCompare(getDisplayName(b)),
  provider: (a: EventGroup, b: EventGroup) => providerLabel(a).localeCompare(providerLabel(b)),
  league: (a: EventGroup, b: EventGroup) => topLeague(a).localeCompare(topLeague(b)),
  matched: (a: EventGroup, b: EventGroup) => (a.matched_count || 0) - (b.matched_count || 0),
  status: (a: EventGroup, b: EventGroup) => (a.enabled ? 1 : 0) - (b.enabled ? 1 : 0),
}

const BY_SORT_ORDER = (a: EventGroup, b: EventGroup) =>
  (a.sort_order ?? 0) - (b.sort_order ?? 0)

export function EventGroups() {
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useGroups(true)
  const { data: leaguesResponse } = useQuery({ queryKey: ["leagues"], queryFn: () => getLeagues() })
  const cachedLeagues = leaguesResponse?.leagues
  const allLeagueSlugs = useMemo(() => cachedLeagues?.map(l => l.slug) ?? [], [cachedLeagues])
  const deleteMutation = useDeleteGroup()
  const { formatDateTime } = useDateFormat()
  // Stale source groups (lylt.2) — their Dispatcharr M3U group is gone.
  const { data: staleGroups = [] } = useQuery({
    queryKey: ["groups", "stale"],
    queryFn: getStaleGroups,
  })
  const staleIds = useMemo(() => new Set(staleGroups.map((g) => g.id)), [staleGroups])
  const toggleMutation = useToggleGroup()
  const previewMutation = usePreviewGroup()
  const clearCacheMutation = useClearGroupMatchCache()
  const clearCachesBulkMutation = useClearGroupsMatchCache()

  // Folders (#1110) — cosmetic arrangement, one level, optional.
  const { data: folderData } = useSourceFolders()
  const folders = useMemo(() => folderData?.folders ?? [], [folderData])
  const canUndo = folderData?.can_undo ?? false
  const arrangementMutation = usePutArrangement()
  const updateFolderMutation = useUpdateSourceFolder()
  const deleteFolderMutation = useDeleteSourceFolder()
  const [renamingFolder, setRenamingFolder] = useState<{ id: number; name: string } | null>(null)

  // Drag-and-drop state: a source row, or a folder header.
  const [draggedGroupId, setDraggedGroupId] = useState<number | null>(null)
  const [draggedFolderId, setDraggedFolderId] = useState<number | null>(null)
  const [dragOverGroupId, setDragOverGroupId] = useState<number | null>(null)
  const [dragOverFolderId, setDragOverFolderId] = useState<number | null>(null)

  // Preview modal state
  const [previewData, setPreviewData] = useState<PreviewGroupResponse | null>(null)
  const [showPreviewModal, setShowPreviewModal] = useState(false)

  // Clear cache confirmation state
  const [clearCacheConfirm, setClearCacheConfirm] = useState<EventGroup | null>(null)
  const [showBulkClearCache, setShowBulkClearCache] = useState(false)

  // Filter state — remembered for the tab's lifetime so editing a source and
  // coming back does not reset the list (#552).
  const [nameFilter, setNameFilter] = usePersistentState("sources.list.name", "")
  const [statusFilter, setStatusFilter] = usePersistentState<"" | "enabled" | "disabled">(
    "sources.list.status",
    ""
  )
  const [providerFilter, setProviderFilter] = usePersistentState("sources.list.provider", "")
  // A league code, or "sport:<code>" for every league of a sport.
  const [leagueFilter, setLeagueFilter] = usePersistentState("sources.list.league", "")

  const [deleteConfirm, setDeleteConfirm] = useState<EventGroup | null>(null)
  const [showBulkDelete, setShowBulkDelete] = useState(false)
  const [showBulkEdit, setShowBulkEdit] = useState(false)
  // Filter groups
  const allGroups = data?.groups
  const filteredGroups = useMemo(() => {
    if (!allGroups) return []

    return allGroups.filter((group) => {
      if (nameFilter && !group.name.toLowerCase().includes(nameFilter.toLowerCase())) return false
      if (statusFilter === "enabled" && !group.enabled) return false
      if (statusFilter === "disabled" && group.enabled) return false
      if (providerFilter && providerLabel(group) !== providerFilter) return false
      if (leagueFilter) {
        const shares = group.league_shares ?? []
        const hit = leagueFilter.startsWith("sport:")
          ? shares.some((s) => s.sport === leagueFilter.slice(6))
          : shares.some((s) => s.league === leagueFilter)
        if (!hit) return false
      }
      return true
    })
  }, [allGroups, nameFilter, statusFilter, providerFilter, leagueFilter])

  // Filter options come from the sources themselves: the providers they
  // belong to, and the sports and leagues their last run matched.
  const providerOptions = useMemo(() => {
    const names = new Set<string>()
    for (const g of allGroups ?? []) {
      const label = providerLabel(g)
      if (label) names.add(label)
    }
    return [{ value: "", label: "All" }, ...[...names].sort().map((n) => ({ value: n, label: n }))]
  }, [allGroups])
  const leagueOptions = useMemo(() => {
    const sports = new Map<string, string>()
    const leagues = new Map<string, string>()
    for (const g of allGroups ?? []) {
      for (const s of g.league_shares ?? []) {
        if (s.sport) sports.set(s.sport, s.sport_display_name || s.sport)
        leagues.set(s.league, s.display_name)
      }
    }
    const bySport = [...sports].sort((a, b) => a[1].localeCompare(b[1]))
    const byLeague = [...leagues].sort((a, b) => a[1].localeCompare(b[1]))
    return [
      { value: "", label: "All" },
      ...bySport.map(([code, label]) => ({ value: `sport:${code}`, label: `All ${label}` })),
      ...byLeague.map(([code, label]) => ({ value: code, label })),
    ]
  }, [allGroups])

  // Column sort: 3-click cycle (asc → desc → reset to the saved arrangement).
  // DnD is only active while unsorted. The arrangement is cosmetic (#1109):
  // processing order and stream priority never read it.
  const { sortColumn, sortDirection, handleSort, clearSort, sortedRows: sortedGroups } =
    useTableSort<EventGroup, SortColumn>({
      rows: filteredGroups,
      comparators: SORT_COMPARATORS,
      cycleToNull: true,
      defaultCompare: BY_SORT_ORDER,
      persistKey: "sources.list",
    })

  const isDndActive = sortColumn === null

  // Folder sections (#1110). Only in the arrangement view: a column sort is a
  // flat list, since a sorted folder would mean nothing. A folder emptied by
  // a filter is hidden; an empty folder with no filter stays as a drop target.
  const sections = useMemo(() => {
    if (!isDndActive || folders.length === 0) return null
    const known = new Set(folders.map((f) => f.id))
    const byFolder = new Map<number | null, EventGroup[]>()
    for (const g of sortedGroups) {
      const key = g.folder_id !== null && known.has(g.folder_id) ? g.folder_id : null
      const list = byFolder.get(key) ?? []
      list.push(g)
      byFolder.set(key, list)
    }
    return {
      folders: folders.map((folder) => ({ folder, groups: byFolder.get(folder.id) ?? [] })),
      loose: byFolder.get(null) ?? [],
    }
  }, [isDndActive, folders, sortedGroups])

  // Sort icon — a plain render helper, not a component (components created
  // during render reset identity; react-hooks/static-components).
  const sortIcon = (column: SortColumn) => {
    if (sortColumn !== column) return <ArrowUpDown className="h-3 w-3 ml-1 opacity-30" />
    return sortDirection === "asc" ? (
      <ArrowUp className="h-3 w-3 ml-1" />
    ) : (
      <ArrowDown className="h-3 w-3 ml-1" />
    )
  }

  const {
    selectedIds,
    toggle: toggleSelect,
    toggleAll: toggleSelectAll,
    setSelectedIds,
  } = useRowSelection(sortedGroups)

  // Overall match rate (shared definition via useMatchRate)
  const matchRate = useMatchRate()

  // League slug -> display name lookup (uses {league} variable resolution: alias first, then name)
  const getLeagueDisplay = useMemo(() => {
    const map = new Map<string, string>()
    for (const league of cachedLeagues ?? []) {
      // {league} variable uses league_alias if available, otherwise name
      map.set(league.slug, getLeagueDisplayName(league, true))
    }
    return (slug: string | null | undefined) => {
      if (!slug) return "-"
      return map.get(slug) ?? slug.toUpperCase()
    }
  }, [cachedLeagues])

  // A detected league hint can name several leagues ("nba, wnba"), which is one
  // string to the map and so would fall through to the raw slug. Resolve each.
  const getLeagueHintDisplay = useMemo(
    () => (hint: string | null | undefined) =>
      !hint
        ? "-"
        : hint
            .split(",")
            .map((slug) => getLeagueDisplay(slug.trim()))
            .join(", "),
    [getLeagueDisplay]
  )

  const handleDelete = async () => {
    if (!deleteConfirm) return

    try {
      const result = await deleteMutation.mutateAsync(deleteConfirm.id)
      toast.success(result.message)
      setDeleteConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete group")
    }
  }


  const handleToggle = async (group: EventGroup) => {
    try {
      await toggleMutation.mutateAsync({
        groupId: group.id,
        enabled: !group.enabled,
      })
      toast.success(`${group.enabled ? "Disabled" : "Enabled"} group "${getDisplayName(group)}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to toggle group")
    }
  }

  const handlePreview = async (group: EventGroup) => {
    try {
      const result = await previewMutation.mutateAsync(group.id)
      setPreviewData(result)
      setShowPreviewModal(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to preview group")
    }
  }

  const handleClearCache = async (group: EventGroup) => {
    try {
      const result = await clearCacheMutation.mutateAsync(group.id)
      toast.success(`Cleared ${result.entries_cleared} cache entries for "${getDisplayName(group)}"`)
      setClearCacheConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to clear cache")
    }
  }

  const handleBulkClearCache = async () => {
    try {
      const result = await clearCachesBulkMutation.mutateAsync(Array.from(selectedIds))
      toast.success(`Cleared ${result.total_cleared} cache entries across ${result.by_group?.length || 0} stream sources`)
      setShowBulkClearCache(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to clear cache")
    }
  }

  // Arrangement (#1110). Every drop is persisted as the full list — each
  // source's folder and position — so a drop can never interleave with rows
  // a filter is hiding. Cosmetic only (#1109): nothing here reaches matching
  // or stream priority.
  const fullOrder = () => [...(allGroups ?? [])].sort(BY_SORT_ORDER)

  const persistSources = async (ordered: EventGroup[], folderOrder?: SourceFolder[]) => {
    const sources: SourcePlacement[] = ordered.map((g, i) => ({
      group_id: g.id,
      folder_id: g.folder_id,
      sort_order: i,
    }))
    try {
      await arrangementMutation.mutateAsync({
        sources,
        folders: folderOrder?.map((f, i) => ({ folder_id: f.id, sort_order: i })),
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save the arrangement")
    }
  }

  const moveGroupBefore = (groupId: number, targetId: number) => {
    const order = fullOrder()
    const dragIndex = order.findIndex((g) => g.id === groupId)
    const target = order.find((g) => g.id === targetId)
    if (dragIndex === -1 || !target) return
    const [dragged] = order.splice(dragIndex, 1)
    const dropIndex = order.findIndex((g) => g.id === targetId)
    order.splice(dropIndex, 0, { ...dragged, folder_id: target.folder_id })
    return persistSources(order)
  }

  const moveGroupsToFolder = (groupIds: Set<number>, folderId: number | null) => {
    const order = fullOrder()
    const moving = order.filter((g) => groupIds.has(g.id)).map((g) => ({ ...g, folder_id: folderId }))
    const rest = order.filter((g) => !groupIds.has(g.id))
    // Append after the folder's last member (or at the very end for the top level).
    let insertAt = rest.length
    for (let i = rest.length - 1; i >= 0; i--) {
      if (rest[i].folder_id === folderId) {
        insertAt = i + 1
        break
      }
    }
    rest.splice(insertAt, 0, ...moving)
    return persistSources(rest)
  }

  const moveFolderBefore = (folderId: number, targetId: number) => {
    const order = [...folders]
    const from = order.findIndex((f) => f.id === folderId)
    if (from === -1) return
    const [dragged] = order.splice(from, 1)
    const to = order.findIndex((f) => f.id === targetId)
    if (to === -1) return
    order.splice(to, 0, dragged)
    return persistSources(fullOrder(), order)
  }

  const clearDrag = () => {
    setDraggedGroupId(null)
    setDraggedFolderId(null)
    setDragOverGroupId(null)
    setDragOverFolderId(null)
  }

  const handleDragStart = (e: React.DragEvent, groupId: number) => {
    setDraggedGroupId(groupId)
    e.dataTransfer.effectAllowed = "move"
    e.dataTransfer.setData("text/plain", String(groupId))
  }

  const handleFolderDragStart = (e: React.DragEvent, folderId: number) => {
    setDraggedFolderId(folderId)
    e.dataTransfer.effectAllowed = "move"
    e.dataTransfer.setData("text/plain", `folder:${folderId}`)
  }

  const handleDragOver = (e: React.DragEvent, targetGroupId: number) => {
    if (draggedGroupId === null) return
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    setDragOverGroupId(targetGroupId)
  }

  const handleFolderDragOver = (e: React.DragEvent, folderId: number) => {
    if (draggedGroupId === null && draggedFolderId === null) return
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    setDragOverFolderId(folderId)
  }

  const handleDrop = async (e: React.DragEvent, targetGroupId: number) => {
    e.preventDefault()
    const groupId = draggedGroupId
    clearDrag()
    if (groupId === null || groupId === targetGroupId) return
    await moveGroupBefore(groupId, targetGroupId)
  }

  const handleFolderDrop = async (e: React.DragEvent, folderId: number) => {
    e.preventDefault()
    const groupId = draggedGroupId
    const fromFolder = draggedFolderId
    clearDrag()
    if (groupId !== null) await moveGroupsToFolder(new Set([groupId]), folderId)
    else if (fromFolder !== null && fromFolder !== folderId) await moveFolderBefore(fromFolder, folderId)
  }

  const handleDragEnd = () => clearDrag()

  // Folder housekeeping
  const toggleFolderCollapsed = (folder: SourceFolder) =>
    updateFolderMutation.mutate({ folderId: folder.id, collapsed: !folder.collapsed })

  const commitRename = async () => {
    if (!renamingFolder) return
    const name = renamingFolder.name.trim()
    setRenamingFolder(null)
    if (!name) return
    try {
      await updateFolderMutation.mutateAsync({ folderId: renamingFolder.id, name })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to rename folder")
    }
  }

  const removeFolder = async (folder: SourceFolder) => {
    try {
      await deleteFolderMutation.mutateAsync(folder.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove folder")
    }
  }

  const handleBulkMove = async (value: string) => {
    if (!value) return
    const folderId = value === "top" ? null : Number(value)
    await moveGroupsToFolder(new Set(selectedIds), folderId)
    const target = folderId === null ? "the top level" : folders.find((f) => f.id === folderId)?.name ?? "folder"
    toast.success(`Moved ${selectedIds.size} source${selectedIds.size > 1 ? "s" : ""} to ${target}`)
    setSelectedIds(new Set())
  }

  // Bulk actions
  const handleBulkToggle = async (enable: boolean) => {
    const groupsToToggle = sortedGroups.filter(
      (g) => selectedIds.has(g.id) && g.enabled !== enable
    )
    for (const group of groupsToToggle) {
      try {
        await toggleMutation.mutateAsync({ groupId: group.id, enabled: enable })
      } catch (err) {
        console.error(`Failed to toggle group ${group.name}:`, err)
      }
    }
    toast.success(`${enable ? "Enabled" : "Disabled"} ${groupsToToggle.length} groups`)
    setSelectedIds(new Set())
  }

  const handleBulkDelete = async () => {
    let deleted = 0
    for (const id of selectedIds) {
      try {
        await deleteMutation.mutateAsync(id)
        deleted++
      } catch (err) {
        console.error(`Failed to delete group ${id}:`, err)
      }
    }
    toast.success(`Deleted ${deleted} groups`)
    setSelectedIds(new Set())
    setShowBulkDelete(false)
  }

  const clearFilters = () => {
    setNameFilter("")
    setStatusFilter("")
    setProviderFilter("")
    setLeagueFilter("")
  }

  const hasActiveFilters = !!nameFilter || statusFilter !== "" || !!providerFilter || !!leagueFilter

  // One source row. Used by the flat (sorted) list and inside folder sections.
  const renderGroupRow = (group: EventGroup) => (
    <TableRow
      key={group.id}
      className={`border-l-3 group/row ${
        draggedGroupId === group.id
          ? "opacity-50 border-l-transparent"
          : dragOverGroupId === group.id
            ? "border-l-transparent border-t-2 border-t-emerald-500"
            : "border-l-transparent hover:border-l-emerald-500"
      }`}
      draggable={isDndActive}
      onDragStart={(e) => isDndActive && handleDragStart(e, group.id)}
      onDragOver={(e) => isDndActive && handleDragOver(e, group.id)}
      onDrop={(e) => isDndActive && handleDrop(e, group.id)}
      onDragEnd={handleDragEnd}
    >
      <TableCell className="px-0 w-6">
        <div
          className={`flex items-center justify-center transition-opacity ${
            isDndActive
              ? "cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
              : "opacity-0 pointer-events-none"
          }`}
          title="Drag to arrange the list or drop onto a folder. Arrangement never affects matching or stream priority."
        >
          <GripVertical className="h-4 w-4" />
        </div>
      </TableCell>
      <TableCell>
        {/* Channel sources (#542) are edited one at a time */}
        {!group.is_channel_source && (
          <Checkbox checked={selectedIds.has(group.id)} onCheckedChange={() => toggleSelect(group.id)} />
        )}
      </TableCell>
      <TableCell className="font-medium">
        <div className="flex items-center gap-2 flex-wrap">
          <span>{getDisplayName(group)}</span>
          {group.is_channel_source && (
            <Badge
              variant="secondary"
              className="text-xs"
              title="Streams come from the channels in this Dispatcharr group, matched through each channel's guide. Selected under Matching → Dispatcharr as a Stream Source."
            >
              Dispatcharr group
            </Badge>
          )}
          {group.is_channel_source && group.source_missing && (
            <Badge
              variant="destructive"
              className="text-xs"
              title="This Dispatcharr channel group no longer exists. Untick it under Matching → Dispatcharr as a Stream Source to remove this source."
            >
              Group missing
            </Badge>
          )}
          {group.managed && (
            <Badge
              variant="info"
              className="text-xs"
              title={
                (group.auto_added_at
                  ? `Added automatically by source discovery on ${group.auto_added_at.slice(0, 10)}. `
                  : "Added from Automation → Discover, or handed over with the Automate switch. ") +
                "It is switched off after the Retire idle window without a match and back on when its group has games again. Switching it off yourself, or turning Automate off, makes it an ordinary source."
              }
            >
              {group.auto_added_at ? "Auto-added" : "Automated"}
            </Badge>
          )}
          {/* Stale-source badge (lylt) */}
          {staleIds.has(group.id) && (
            <Badge variant="destructive" className="text-xs" title="This source's M3U group no longer exists in Dispatcharr">
              Source missing
            </Badge>
          )}
          {/* Regex badge */}
          {(group.custom_regex_teams_enabled ||
            group.custom_regex_date_enabled ||
            group.custom_regex_month_enabled ||
            group.custom_regex_day_enabled ||
            group.custom_regex_time_enabled ||
            group.custom_regex_league_enabled ||
            group.custom_regex_fighters_enabled ||
            group.custom_regex_event_name_enabled ||
            group.stream_include_regex_enabled ||
            group.stream_exclude_regex_enabled) && (
            <Badge
              variant="secondary"
              className="bg-blue-500/15 text-blue-400 border-blue-500/30 text-xs"
              title={`Custom regex: ${[
                group.custom_regex_teams_enabled && "teams",
                group.custom_regex_date_enabled && "date",
                group.custom_regex_month_enabled && "month",
                group.custom_regex_day_enabled && "day",
                group.custom_regex_time_enabled && "time",
                group.custom_regex_league_enabled && "league",
                group.custom_regex_fighters_enabled && "fighters",
                group.custom_regex_event_name_enabled && "event name",
                group.stream_include_regex_enabled && "include",
                group.stream_exclude_regex_enabled && "exclude",
              ].filter(Boolean).join(", ")}`}
            >
              Regex
            </Badge>
          )}
          {/* Stream Name Matching badge */}
          {group.name_match_enabled && (
            <Badge
              variant="secondary"
              className="bg-sky-500/15 text-sky-400 border-sky-500/30 text-xs"
              title="Stream name matching: streams whose name identifies a specific event (e.g. &quot;Bills vs Dolphins&quot;)"
            >
              Stream Name
            </Badge>
          )}
          {/* Team Streams badge */}
          {group.team_streams_enabled && (
            <Badge
              variant="secondary"
              className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs"
              title="Team stream source: team-branded streams match events where that team plays"
            >
              Team
            </Badge>
          )}
          {/* EPG Program Matching badge */}
          {group.epg_match_enabled && (
            <Badge
              variant="secondary"
              className="bg-violet-500/15 text-violet-400 border-violet-500/30 text-xs"
              title="EPG program matching: static-named linear channels matched to events via Dispatcharr's program guide"
            >
              EPG
            </Badge>
          )}
        </div>
      </TableCell>
      {/* Provider (#1110): the M3U account, or Dispatcharr for a channel source. */}
      <TableCell>
        {providerLabel(group) && (
          <Badge
            variant="secondary"
            className="text-xs max-w-full truncate cursor-pointer"
            title={group.is_channel_source ? "Dispatcharr channel source" : `M3U Account: ${group.m3u_account_name}`}
            onClick={() => setProviderFilter(providerLabel(group))}
          >
            {providerLabel(group)}
          </Badge>
        )}
      </TableCell>
      {/* Leagues (#1110): what this source matched in the last run. */}
      <TableCell>
        <LeagueChips
          shares={group.league_shares ?? []}
          runAt={group.league_shares_run_at}
          formatDateTime={formatDateTime}
          onPick={(league) => setLeagueFilter(league)}
        />
      </TableCell>
      {/* Matched Column with Progress Bar */}
      <TableCell className="text-center">
        {/* Coverage % is only meaningful when Stream Name matching is on
            (~1 stream → 1 event). A pure Team/EPG source fans one stream
            out to many events, so show raw stream volume instead. */}
        {!group.name_match_enabled ? (
          <span className="text-[0.65rem] text-muted-foreground" title={`Last: ${group.last_refresh ? formatDateTime(group.last_refresh) : 'Never'}`}>
            {group.stream_count ?? 0} streams
          </span>
        ) : group.stream_count && group.stream_count > 0 ? (
          <RichTooltip
            side="top"
            content={
              <div className="space-y-1 text-xs">
                <div>{group.match_result_count ?? 0} match{(group.match_result_count ?? 0) === 1 ? "" : "es"} produced</div>
                {(group.match_result_count ?? 0) > (group.matched_count ?? 0) && (
                  <div className="text-muted-foreground">EPG time-sharing: streams matched to multiple events</div>
                )}
                <div className="text-muted-foreground">Coverage: matched streams over eligible streams.</div>
                <div className="text-muted-foreground">Last: {group.last_refresh ? formatDateTime(group.last_refresh) : 'Never'}</div>
              </div>
            }
          >
            <div className="flex flex-col items-center gap-0.5">
              <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    (group.matched_count || 0) / group.stream_count >= 0.8
                      ? 'bg-green-500'
                      : (group.matched_count || 0) / group.stream_count >= 0.5
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.min(100, Math.round(((group.matched_count || 0) / group.stream_count) * 100))}%` }}
                />
              </div>
              <span className="text-[0.65rem]">
                {group.matched_count}/{group.stream_count} ({Math.round(((group.matched_count || 0) / group.stream_count) * 100)}%)
              </span>
            </div>
          </RichTooltip>
        ) : (
          <span className="text-muted-foreground text-xs italic">—</span>
        )}
      </TableCell>
      <TableCell>
        <Switch
          checked={group.enabled}
          onCheckedChange={() => handleToggle(group)}
          disabled={toggleMutation.isPending || !!group.is_channel_source}
          title={
            group.is_channel_source
              ? "Select or deselect this group under Matching → Dispatcharr as a Stream Source"
              : undefined
          }
        />
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => handlePreview(group)}
            disabled={previewMutation.isPending}
            title="Preview stream matches"
          >
            {previewMutation.isPending && previewMutation.variables === group.id ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setClearCacheConfirm(group)}
            disabled={clearCacheMutation.isPending}
            title="Clear match cache"
          >
            {clearCacheMutation.isPending && clearCacheMutation.variables === group.id ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate(`/sources/${group.id}`)} title="Edit">
            <Pencil className="h-4 w-4" />
          </Button>
          {!group.is_channel_source && (
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setDeleteConfirm(group)} title="Delete">
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )

  // A folder header row (#1110): collapse, select-all, name (click to rename),
  // count, aggregate coverage, remove. A drop target for sources and, when a
  // folder header is being dragged, for folder reordering.
  const renderFolderRow = (folder: SourceFolder, groups: EventGroup[]) => {
    const selectable = groups.filter((g) => !g.is_channel_source)
    const allSelected = selectable.length > 0 && selectable.every((g) => selectedIds.has(g.id))
    const eligible = groups.reduce((n, g) => n + (g.name_match_enabled ? g.stream_count || 0 : 0), 0)
    const matched = groups.reduce((n, g) => n + (g.name_match_enabled ? g.matched_count || 0 : 0), 0)
    const isRenaming = renamingFolder?.id === folder.id
    return (
      <TableRow
        key={`folder-${folder.id}`}
        className={`bg-muted/40 hover:bg-muted/60 ${
          draggedFolderId === folder.id
            ? "opacity-50"
            : dragOverFolderId === folder.id
              ? "border-t-2 border-t-emerald-500"
              : ""
        }`}
        draggable={isDndActive && !isRenaming}
        onDragStart={(e) => handleFolderDragStart(e, folder.id)}
        onDragOver={(e) => handleFolderDragOver(e, folder.id)}
        onDrop={(e) => handleFolderDrop(e, folder.id)}
        onDragEnd={handleDragEnd}
      >
        <TableCell className="px-0 w-6">
          <div className="flex items-center justify-center cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground" title="Drag to reorder folders">
            <GripVertical className="h-4 w-4" />
          </div>
        </TableCell>
        <TableCell>
          {selectable.length > 0 && (
            <div title="Select every source in this folder">
              <Checkbox
                checked={allSelected}
                onCheckedChange={() => {
                  const next = new Set(selectedIds)
                  for (const g of selectable) {
                    if (allSelected) next.delete(g.id)
                    else next.add(g.id)
                  }
                  setSelectedIds(next)
                }}
              />
            </div>
          )}
        </TableCell>
        <TableCell colSpan={4}>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground"
              onClick={() => toggleFolderCollapsed(folder)}
              title={folder.collapsed ? "Expand" : "Collapse"}
            >
              {folder.collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            <Folder className="h-4 w-4 text-muted-foreground" />
            {isRenaming ? (
              <Input
                autoFocus
                value={renamingFolder.name}
                onChange={(e) => setRenamingFolder({ id: folder.id, name: e.target.value })}
                onBlur={() => void commitRename()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void commitRename()
                  if (e.key === "Escape") setRenamingFolder(null)
                }}
                className="h-6 text-sm px-1 max-w-xs"
              />
            ) : (
              <button
                type="button"
                className="font-semibold text-sm hover:underline"
                onClick={() => setRenamingFolder({ id: folder.id, name: folder.name })}
                title="Click to rename"
              >
                {folder.name}
              </button>
            )}
            <span className="text-xs text-muted-foreground">
              {groups.length} source{groups.length === 1 ? "" : "s"}
              {eligible > 0 && (
                <>
                  {" · "}
                  <span className={matchRateColor(Math.round((matched / eligible) * 100))}>
                    {Math.round((matched / eligible) * 100)}%
                  </span>{" "}
                  matched
                </>
              )}
            </span>
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center justify-end">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => removeFolder(folder)}
              disabled={deleteFolderMutation.isPending}
              title="Remove folder (its sources move to the top level)"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </TableCell>
      </TableRow>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Sources</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Error loading groups: {error.message}
            </p>
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
      {/* Header - Compact */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold">Sources</h1>
          {matchRate.hasData && (
            <span className="text-sm text-muted-foreground">
              <span className={`font-semibold ${matchRateColor(matchRate.rate)}`}>{matchRate.rate}%</span> matched
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArrangeMenu folderCount={folders.length} canUndo={canUndo} />
          <Button size="sm" onClick={() => navigate("/sources/import")}>
            <Plus className="h-4 w-4 mr-1" />
            Add Stream Source
          </Button>
        </div>
      </div>


      <SourceAutomation leagueName={getLeagueDisplay} />

      {/* Fixed Batch Operations Bar */}
      {selectedIds.size > 0 && (
        <StickyActionBar
          label={
            <>
                {selectedIds.size} stream source{selectedIds.size > 1 ? "s" : ""} selected
            </>
          }
        >
                <Button variant="outline" size="sm" onClick={() => setSelectedIds(new Set())}>
                  Clear
                </Button>
                <FilterSelect
                  value=""
                  onChange={(v) => void handleBulkMove(v)}
                  placeholder="Move to folder…"
                  className="h-8 text-sm"
                  options={[
                    { value: "", label: "Move to folder…" },
                    { value: "top", label: "Top level" },
                    ...folders.map((f) => ({ value: String(f.id), label: f.name })),
                  ]}
                />
                <Button variant="outline" size="sm" onClick={() => handleBulkToggle(true)}>
                  Enable
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleBulkToggle(false)}>
                  Disable
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowBulkClearCache(true)}
                  disabled={clearCachesBulkMutation.isPending}
                >
                  <RotateCcw className="h-3 w-3 mr-1" />
                  Clear Cache
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (selectedIds.size === 1) {
                      const groupId = Array.from(selectedIds)[0]
                      navigate(`/sources/${groupId}`)
                    } else {
                      setShowBulkEdit(true)
                    }
                  }}
                  title={selectedIds.size === 1 ? "Edit group" : "Edit selected groups"}
                >
                  <Pencil className="h-3 w-3 mr-1" />
                  Edit
                </Button>
                <Button variant="destructive" size="sm" onClick={() => setShowBulkDelete(true)}>
                  <Trash2 className="h-3 w-3 mr-1" />
                  Delete
                </Button>
        </StickyActionBar>
      )}

      {/* Groups Table - No card wrapper for more compact look */}
      <div className="border border-border rounded-lg overflow-hidden">
          {isLoading ? (
            <Spinner />
          ) : data?.groups.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No stream sources configured. Add one to get started.
            </div>
          ) : (
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-6 px-0"></TableHead>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={selectedIds.size === sortedGroups.length && sortedGroups.length > 0}
                      onCheckedChange={toggleSelectAll}
                    />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("name")}
                  >
                    <div className="flex items-center">
                      Name {sortIcon("name")}
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-32 cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("provider")}
                  >
                    <div className="flex items-center">
                      Provider {sortIcon("provider")}
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-56 cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("league")}
                    title="Leagues this source matched in the last run, with each league's share of its matched streams"
                  >
                    <div className="flex items-center">
                      Leagues {sortIcon("league")}
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-24 text-center cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("matched")}
                  >
                    <div className="flex items-center justify-center">
                      Matched {sortIcon("matched")}
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-14 cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("status")}
                  >
                    <div className="flex items-center">
                      Status {sortIcon("status")}
                    </div>
                  </TableHead>
                  <TableHead className="w-28 text-right">
                    {sortColumn !== null ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-5 px-1.5 text-xs"
                        onClick={clearSort}
                        title="Back to your arrangement"
                      >
                        <RotateCcw className="h-3 w-3 mr-1" />
                        Arrangement
                      </Button>
                    ) : (
                      "Actions"
                    )}
                  </TableHead>
                </TableRow>
                {/* Filter row */}
                <TableRow className="border-b-2 border-border">
                  <TableHead className="py-0.5 pb-1.5 w-6 px-0"></TableHead>
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
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect value={providerFilter} onChange={setProviderFilter} options={providerOptions} />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect value={leagueFilter} onChange={setLeagueFilter} options={leagueOptions} />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5"></TableHead>
                  <TableHead className="py-0.5 pb-1.5">
                    <FilterSelect
                      value={statusFilter}
                      onChange={(v) => setStatusFilter(v as typeof statusFilter)}
                      options={[
                        { value: "", label: "All" },
                        { value: "enabled", label: "Active" },
                        { value: "disabled", label: "Inactive" },
                      ]}
                    />
                  </TableHead>
                  <TableHead className="py-0.5 pb-1.5 text-right">
                    {hasActiveFilters && (
                      <Button variant="ghost" size="sm" onClick={clearFilters} className="h-5 px-1.5">
                        <X className="h-3 w-3" />
                      </Button>
                    )}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedGroups.length === 0 && (!sections || sections.folders.every((f) => f.groups.length === 0)) ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                      No stream sources match the current filters.
                    </TableCell>
                  </TableRow>
                ) : sections ? (
                  <>
                    {sections.folders.map(({ folder, groups }) => {
                      if (groups.length === 0 && hasActiveFilters) return null
                      return (
                        <React.Fragment key={folder.id}>
                          {renderFolderRow(folder, groups)}
                          {!folder.collapsed && groups.map(renderGroupRow)}
                          {!folder.collapsed && groups.length === 0 && (
                            <TableRow>
                              <TableCell colSpan={8} className="py-2 text-center text-xs text-muted-foreground italic">
                                Empty folder — drop sources here or use Move to folder.
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      )
                    })}
                    {sections.loose.length > 0 && sections.folders.length > 0 && (
                      <TableRow className="bg-muted/20">
                        <TableCell colSpan={8} className="py-1 text-[0.65rem] uppercase tracking-wide text-muted-foreground">
                          Not in a folder
                        </TableCell>
                      </TableRow>
                    )}
                    {sections.loose.map(renderGroupRow)}
                  </>
                ) : (
                  sortedGroups.map(renderGroupRow)
                )}
              </TableBody>
            </Table>
          )}
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        title="Delete Stream Source"
        description={`Are you sure you want to delete "${deleteConfirm ? getDisplayName(deleteConfirm) : ""}"? This will also delete all ${deleteConfirm?.channel_count ?? 0} managed channels associated with this stream source.`}
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
      />

      {/* Clear Cache Confirmation Dialog */}
      <ConfirmDialog
        open={clearCacheConfirm !== null}
        onOpenChange={(open) => !open && setClearCacheConfirm(null)}
        title="Clear Match Cache"
        description={`Clear the stream match cache for "${clearCacheConfirm ? getDisplayName(clearCacheConfirm) : ""}"? This will force re-matching on the next EPG generation run.`}
        confirmLabel="Clear Cache"
        confirmVariant="default"
        isPending={clearCacheMutation.isPending}
        onConfirm={() => clearCacheConfirm && handleClearCache(clearCacheConfirm)}
      />

      {/* Bulk Clear Cache Confirmation Dialog */}
      <ConfirmDialog
        open={showBulkClearCache}
        onOpenChange={setShowBulkClearCache}
        title={`Clear Match Cache for ${selectedIds.size} Stream Sources`}
        description={`Clear the stream match cache for ${selectedIds.size} selected stream sources? This will force re-matching on the next EPG generation run.`}
        confirmLabel={`Clear Cache for ${selectedIds.size} Stream Sources`}
        confirmVariant="default"
        isPending={clearCachesBulkMutation.isPending}
        onConfirm={handleBulkClearCache}
      />

      {/* Bulk Edit Dialog */}
      <BulkEditDialog
        open={showBulkEdit}
        onOpenChange={setShowBulkEdit}
        selectedIds={selectedIds}
        allLeagueSlugs={allLeagueSlugs}
        onSuccess={() => setSelectedIds(new Set())}
      />

      {/* Bulk Delete Confirmation Dialog */}
      <ConfirmDialog
        open={showBulkDelete}
        onOpenChange={setShowBulkDelete}
        title={`Delete ${selectedIds.size} Stream Sources`}
        description={`Are you sure you want to delete ${selectedIds.size} stream sources? This will also delete all managed channels associated with them.`}
        confirmLabel={`Delete ${selectedIds.size} Groups`}
        isPending={deleteMutation.isPending}
        onConfirm={handleBulkDelete}
      />

      {/* Stream Preview Modal */}
      <Dialog open={showPreviewModal} onOpenChange={setShowPreviewModal}>
        <DialogContent onClose={() => setShowPreviewModal(false)} className="max-w-5xl max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>
              Stream Preview: {previewData?.group_name}
            </DialogTitle>
            <DialogDescription>
              Preview of stream matching results. Processing is done via EPG generation.
            </DialogDescription>
          </DialogHeader>

          {previewData && (
            <div className="flex-1 overflow-hidden flex flex-col gap-4">
              {/* Summary stats */}
              <div className="flex items-center gap-4 p-3 bg-muted/50 rounded-lg text-sm">
                <span>{previewData.total_streams} streams</span>
                <span className="text-muted-foreground">|</span>
                <span className="text-green-600 dark:text-green-400">
                  {previewData.matched_count} matched
                </span>
                <span className="text-muted-foreground">|</span>
                <span className="text-amber-600 dark:text-amber-400">
                  {previewData.unmatched_count} unmatched
                </span>
                {previewData.filtered_count > 0 && (
                  <>
                    <span className="text-muted-foreground">|</span>
                    <span className="text-muted-foreground">
                      {previewData.filtered_count} filtered
                    </span>
                  </>
                )}
                {previewData.cache_hits > 0 && (
                  <>
                    <span className="text-muted-foreground">|</span>
                    <span className="text-muted-foreground">
                      {previewData.cache_hits}/{previewData.cache_hits + previewData.cache_misses} cached
                    </span>
                  </>
                )}
              </div>

              {/* Errors */}
              {previewData.errors.length > 0 && (
                <Alert variant="destructive">
                  {previewData.errors.map((err, i) => (
                    <div key={i}>{err}</div>
                  ))}
                </Alert>
              )}

              {/* Stream table */}
              <div className="flex-1 overflow-auto border rounded-lg">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10">Status</TableHead>
                      <TableHead className="w-[40%]">Stream Name</TableHead>
                      <TableHead>League</TableHead>
                      <TableHead>Event Match</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewData.streams.map((stream, i) => (
                      <TableRow key={i}>
                        <TableCell>
                          {stream.matched ? (
                            <Check className="h-4 w-4 text-green-600 dark:text-green-400" />
                          ) : (
                            <CircleAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          <div className="break-all">{stream.stream_name}</div>
                          {!stream.matched &&
                            (stream.parsed_team1 ||
                              stream.parsed_team2 ||
                              stream.extracted_date ||
                              stream.extracted_time) && (
                              <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-sans font-normal text-muted-foreground mt-1.5">
                                <span className="text-muted-foreground/70 font-medium">Extracted:</span>
                                {stream.parsed_team1 && (
                                  <span className="bg-muted/70 px-1.5 py-0.5 rounded border border-border/40">
                                    <span className="text-muted-foreground/60 font-medium">T1:</span>{" "}
                                    <span className="text-foreground/90 font-mono text-[10.5px]">
                                      {stream.parsed_team1}
                                    </span>
                                  </span>
                                )}
                                {stream.parsed_team2 && (
                                  <span className="bg-muted/70 px-1.5 py-0.5 rounded border border-border/40">
                                    <span className="text-muted-foreground/60 font-medium">T2:</span>{" "}
                                    <span className="text-foreground/90 font-mono text-[10.5px]">
                                      {stream.parsed_team2}
                                    </span>
                                  </span>
                                )}
                                {(stream.extracted_date || stream.extracted_time) && (
                                  <span className="bg-muted/70 px-1.5 py-0.5 rounded border border-border/40">
                                    <span className="text-muted-foreground/60 font-medium">When:</span>{" "}
                                    <span className="text-foreground/90">
                                      {[
                                        stream.extracted_date,
                                        stream.extracted_time,
                                        stream.extracted_tz ? `(${stream.extracted_tz})` : null,
                                      ]
                                        .filter(Boolean)
                                        .join(" ")}
                                    </span>
                                  </span>
                                )}
                              </div>
                            )}
                        </TableCell>
                        <TableCell>
                          {stream.league ? (
                            <Badge variant="secondary">{getLeagueDisplay(stream.league)}</Badge>
                          ) : stream.detected_league ? (
                            <Badge
                              variant="outline"
                              className="border-dashed text-muted-foreground text-xs"
                              title="Detected league hint"
                            >
                              {getLeagueHintDisplay(stream.detected_league)}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {stream.matched ? (
                            <div className="text-sm">
                              <div className="font-medium">{stream.event_name}</div>
                              {stream.start_time && (
                                <div className="text-muted-foreground text-xs">
                                  {formatDateTime(stream.start_time)}
                                </div>
                              )}
                              {stream.epg_programmes && stream.epg_programmes.length > 0 && (
                                <details className="mt-1 text-xs text-muted-foreground">
                                  <summary className="cursor-pointer">
                                    {stream.epg_programmes.length} other guide programme
                                    {stream.epg_programmes.length === 1 ? "" : "s"} looked like a
                                    game and matched nothing
                                  </summary>
                                  <ul className="mt-1 space-y-0.5 pl-3 border-l border-border">
                                    {stream.epg_programmes.map((p, i) => (
                                      <li key={i} className="break-words">
                                        {p.title}
                                        {p.start && ` · ${formatDateTime(p.start)}`}
                                        {" — "}
                                        {getFailedReasonLabel(p.reason)}
                                      </li>
                                    ))}
                                  </ul>
                                </details>
                              )}
                            </div>
                          ) : (
                            <div className="text-xs text-muted-foreground">
                              <div>
                                {getFailedReasonLabel(
                                  stream.failed_reason || stream.exclusion_reason || "unmatched"
                                )}
                              </div>
                              {stream.detail && (
                                <div className="text-muted-foreground/70 mt-0.5 break-words">
                                  {stream.detail}
                                </div>
                              )}
                              {stream.epg_programmes && stream.epg_programmes.length > 0 && (
                                <details className="mt-1">
                                  <summary className="cursor-pointer text-foreground/80">
                                    {stream.epg_programmes.length} guide programme
                                    {stream.epg_programmes.length === 1 ? "" : "s"} looked like a
                                    game and matched nothing
                                  </summary>
                                  <ul className="mt-1 space-y-0.5 pl-3 border-l border-border">
                                    {stream.epg_programmes.map((p, i) => (
                                      <li key={i} className="break-words">
                                        <span className="text-foreground/80">{p.title}</span>
                                        {p.start && (
                                          <span className="text-muted-foreground/70">
                                            {" · "}
                                            {formatDateTime(p.start)}
                                          </span>
                                        )}
                                        <span className="text-muted-foreground/70">
                                          {" — "}
                                          {getFailedReasonLabel(p.reason)}
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </details>
                              )}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                    {previewData.streams.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                          No streams to display
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPreviewModal(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  )
}
