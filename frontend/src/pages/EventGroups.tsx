import React, { useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import {
  Search,
  Trash2,
  Pencil,
  Loader2,
  Plus,
  X,
  Check,
  AlertCircle,
  GripVertical,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  RotateCcw,
} from "lucide-react"
import { Alert } from "@/components/ui/alert"
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
import { Input } from "@/components/ui/input"
import {
  useBulkUpdateGroups,
  useClearGroupMatchCache,
  useClearGroupsMatchCache,
  useGroups,
  useDeleteGroup,
  useToggleGroup,
  usePreviewGroup,
  useReorderGroups,
} from "@/hooks/useGroups"
import { useMatchRate, matchRateColor } from "@/hooks/useMatchRate"
import type { EventGroup, PreviewGroupResponse, TeamFilterEntry } from "@/api/types"
import { getStaleGroups } from "@/api/groups"
import { useDateFormat } from "@/hooks/useDateFormat"
import { getLeagues } from "@/api/teams"
import { StreamTimezoneSelector } from "@/components/StreamTimezoneSelector"
import { TeamPicker } from "@/components/TeamPicker"
import { Label } from "@/components/ui/label"
import { getLeagueDisplayName } from "@/lib/utils"

// Helper to get display name (prefer display_name over name)
const getDisplayName = (group: EventGroup) => group.display_name || group.name

export function EventGroups() {
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useGroups(true)
  const { data: leaguesResponse } = useQuery({ queryKey: ["leagues"], queryFn: () => getLeagues() })
  const cachedLeagues = leaguesResponse?.leagues
  const allLeagueSlugs = useMemo(() => cachedLeagues?.map(l => l.slug) ?? [], [cachedLeagues])
  const deleteMutation = useDeleteGroup()
  const { formatRelativeTime } = useDateFormat()
  // Stale source groups (lylt.2) — their Dispatcharr M3U group is gone.
  const { data: staleGroups = [] } = useQuery({
    queryKey: ["groups", "stale"],
    queryFn: getStaleGroups,
  })
  const [showStaleDelete, setShowStaleDelete] = useState(false)
  const [deletingStale, setDeletingStale] = useState(false)
  const staleIds = useMemo(() => new Set(staleGroups.map((g) => g.id)), [staleGroups])
  const toggleMutation = useToggleGroup()
  const bulkUpdateMutation = useBulkUpdateGroups()
  const previewMutation = usePreviewGroup()
  const clearCacheMutation = useClearGroupMatchCache()
  const clearCachesBulkMutation = useClearGroupsMatchCache()
  const reorderMutation = useReorderGroups()

  // Drag-and-drop state
  const [draggedGroupId, setDraggedGroupId] = useState<number | null>(null)
  const [dragOverGroupId, setDragOverGroupId] = useState<number | null>(null)

  // Preview modal state
  const [previewData, setPreviewData] = useState<PreviewGroupResponse | null>(null)
  const [showPreviewModal, setShowPreviewModal] = useState(false)

  // Clear cache confirmation state
  const [clearCacheConfirm, setClearCacheConfirm] = useState<EventGroup | null>(null)
  const [showBulkClearCache, setShowBulkClearCache] = useState(false)

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // Filter state
  const [nameFilter, setNameFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState<"" | "enabled" | "disabled">("")

  const [deleteConfirm, setDeleteConfirm] = useState<EventGroup | null>(null)
  const [showBulkDelete, setShowBulkDelete] = useState(false)
  const [showBulkEdit, setShowBulkEdit] = useState(false)
  // Bulk edit form state - checkboxes control which fields to update
  const [bulkEditStreamTimezoneEnabled, setBulkEditStreamTimezoneEnabled] = useState(false)
  const [bulkEditStreamTimezone, setBulkEditStreamTimezone] = useState<string | null>(null)
  const [bulkEditClearStreamTimezone, setBulkEditClearStreamTimezone] = useState(false)
  // Team filter bulk edit state
  const [bulkEditTeamFilterEnabled, setBulkEditTeamFilterEnabled] = useState(false)
  const [bulkEditTeamFilterAction, setBulkEditTeamFilterAction] = useState<"set" | "clear">("set")
  const [bulkEditTeamFilterMode, setBulkEditTeamFilterMode] = useState<"include" | "exclude">("include")
  const [bulkEditTeamFilterTeams, setBulkEditTeamFilterTeams] = useState<TeamFilterEntry[]>([])
  const [bulkEditBypassPlayoffs, setBulkEditBypassPlayoffs] = useState(false)
  const [bulkEditTeamStreamsEnabled, setBulkEditTeamStreamsEnabled] = useState(false)
  const [bulkEditTeamStreams, setBulkEditTeamStreams] = useState(false)
  const [bulkEditEPGMatchEnabled, setBulkEditEPGMatchEnabled] = useState(false)
  const [bulkEditEPGMatch, setBulkEditEPGMatch] = useState(false)
  // Column sorting state
  type SortColumn = "name" | "matched" | "status" | null
  type SortDirection = "asc" | "desc"
  const [sortColumn, setSortColumn] = useState<SortColumn>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc")

  // Handle column sort (3-click cycle: asc → desc → reset to sort_order)
  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      if (sortDirection === "asc") {
        setSortDirection("desc")
      } else {
        // Third click: reset to default sort_order
        setSortColumn(null)
        setSortDirection("asc")
      }
    } else {
      setSortColumn(column)
      setSortDirection("asc")
    }
  }

  const isDndActive = sortColumn === null

  // Sort icon component
  const SortIcon = ({ column }: { column: SortColumn }) => {
    if (sortColumn !== column) return <ArrowUpDown className="h-3 w-3 ml-1 opacity-30" />
    return sortDirection === "asc" ? (
      <ArrowUp className="h-3 w-3 ml-1" />
    ) : (
      <ArrowDown className="h-3 w-3 ml-1" />
    )
  }

  // Filter groups
  const filteredGroups = useMemo(() => {
    if (!data?.groups) return []

    return data.groups.filter((group) => {
      if (nameFilter && !group.name.toLowerCase().includes(nameFilter.toLowerCase())) return false
      if (statusFilter === "enabled" && !group.enabled) return false
      if (statusFilter === "disabled" && group.enabled) return false
      return true
    })
  }, [data?.groups, nameFilter, statusFilter])

  // Apply column sorting when a column header is clicked, default to sort_order
  const sortedGroups = useMemo(() => {
    if (!sortColumn) {
      return [...filteredGroups].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    }

    const sortFn = (a: EventGroup, b: EventGroup) => {
      let cmp = 0
      switch (sortColumn) {
        case "name":
          cmp = getDisplayName(a).localeCompare(getDisplayName(b))
          break
        case "matched":
          cmp = (a.matched_count || 0) - (b.matched_count || 0)
          break
        case "status":
          cmp = (a.enabled ? 1 : 0) - (b.enabled ? 1 : 0)
          break
      }
      return sortDirection === "asc" ? cmp : -cmp
    }

    return [...filteredGroups].sort(sortFn)
  }, [filteredGroups, sortColumn, sortDirection])

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

  const handleDeleteAllStale = async () => {
    setDeletingStale(true)
    try {
      const results = await Promise.allSettled(
        staleGroups.map((g) => deleteMutation.mutateAsync(g.id)),
      )
      const ok = results.filter((r) => r.status === "fulfilled").length
      const failed = results.length - ok
      if (failed === 0) toast.success(`Deleted ${ok} stale source${ok === 1 ? "" : "s"}`)
      else toast.warning(`Deleted ${ok}, failed ${failed}`)
      setShowStaleDelete(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete stale sources")
    } finally {
      setDeletingStale(false)
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

  // Drag-and-drop handlers (only active in default sort_order mode)
  const handleDragStart = (e: React.DragEvent, groupId: number) => {
    setDraggedGroupId(groupId)
    e.dataTransfer.effectAllowed = "move"
    e.dataTransfer.setData("text/plain", String(groupId))
  }

  const handleDragOver = (e: React.DragEvent, targetGroupId: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    setDragOverGroupId(targetGroupId)
  }

  const handleDrop = async (e: React.DragEvent, targetGroupId: number) => {
    e.preventDefault()
    setDraggedGroupId(null)
    setDragOverGroupId(null)

    if (draggedGroupId === null || draggedGroupId === targetGroupId) return

    // Build new order from current sortedGroups
    const currentOrder = [...sortedGroups]
    const dragIndex = currentOrder.findIndex(g => g.id === draggedGroupId)
    const dropIndex = currentOrder.findIndex(g => g.id === targetGroupId)
    if (dragIndex === -1 || dropIndex === -1) return

    // Move dragged item to drop position
    const [dragged] = currentOrder.splice(dragIndex, 1)
    currentOrder.splice(dropIndex, 0, dragged)

    // Assign sequential sort_order values and persist
    const reorderPayload = currentOrder.map((g, i) => ({
      group_id: g.id,
      sort_order: i,
    }))

    try {
      await reorderMutation.mutateAsync(reorderPayload)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reorder groups")
    }
  }

  const handleDragEnd = () => {
    setDraggedGroupId(null)
    setDragOverGroupId(null)
  }

  // Selection handlers
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === sortedGroups.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(sortedGroups.map((g) => g.id)))
    }
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

  // Reset bulk edit form state
  const resetBulkEditForm = () => {
    setBulkEditStreamTimezoneEnabled(false)
    setBulkEditStreamTimezone(null)
    setBulkEditClearStreamTimezone(false)
    setBulkEditTeamFilterEnabled(false)
    setBulkEditTeamFilterAction("set")
    setBulkEditTeamFilterMode("include")
    setBulkEditTeamFilterTeams([])
    setBulkEditBypassPlayoffs(false)
    setBulkEditTeamStreamsEnabled(false)
    setBulkEditTeamStreams(false)
  }

  const handleBulkEdit = async () => {
    const ids = Array.from(selectedIds)

    // Build request with only enabled fields
    const request: Record<string, unknown> & { group_ids: number[] } = { group_ids: ids }

    if (bulkEditStreamTimezoneEnabled) {
      if (bulkEditClearStreamTimezone) {
        request.clear_stream_timezone = true
      } else if (bulkEditStreamTimezone) {
        request.stream_timezone = bulkEditStreamTimezone
      }
    }

    if (bulkEditTeamStreamsEnabled) {
      request.team_streams_enabled = bulkEditTeamStreams
    }

    if (bulkEditEPGMatchEnabled) {
      request.epg_match_enabled = bulkEditEPGMatch
    }

    if (bulkEditTeamFilterEnabled) {
      if (bulkEditTeamFilterAction === "clear") {
        // Reset to global default
        request.clear_include_teams = true
        request.clear_exclude_teams = true
        request.clear_bypass_filter_for_playoffs = true
      } else {
        // Set custom filter
        request.team_filter_mode = bulkEditTeamFilterMode
        request.bypass_filter_for_playoffs = bulkEditBypassPlayoffs
        if (bulkEditTeamFilterMode === "include") {
          request.include_teams = bulkEditTeamFilterTeams
          request.clear_exclude_teams = true
        } else {
          request.exclude_teams = bulkEditTeamFilterTeams
          request.clear_include_teams = true
        }
      }
    }

    try {
      const result = await bulkUpdateMutation.mutateAsync(request)
      if (result.total_failed > 0) {
        toast.warning(`Updated ${result.total_updated} groups, ${result.total_failed} failed`)
      } else {
        toast.success(`Updated ${result.total_updated} groups`)
      }
      setSelectedIds(new Set())
      setShowBulkEdit(false)
      resetBulkEditForm()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update groups")
    }
  }

  const clearFilters = () => {
    setNameFilter("")
    setStatusFilter("")
  }

  const hasActiveFilters = nameFilter || statusFilter !== ""

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
        <Button size="sm" onClick={() => navigate("/sources/import")}>
          <Plus className="h-4 w-4 mr-1" />
          Add Stream Source
        </Button>
      </div>


      {/* Stale sources — their Dispatcharr M3U group is gone (lylt.2) */}
      {staleGroups.length > 0 && (
        <Alert
          variant="warning"
          icon={<AlertCircle />}
          title={`${staleGroups.length} stream source${staleGroups.length === 1 ? "" : "s"} missing from Dispatcharr`}
        >
          <div className="space-y-2">
            <p className="text-sm">
              {staleGroups.length === 1
                ? "Its M3U group was removed or renamed in Dispatcharr, so it can no longer pull streams. Delete it, or restore the source in Dispatcharr."
                : "Their M3U groups were removed or renamed in Dispatcharr, so they can no longer pull streams. Delete them, or restore the sources in Dispatcharr."}
            </p>
            <ul className="space-y-0.5 text-sm">
              {staleGroups.map((g) => (
                <li key={g.id} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium">{g.display_name || g.name}</span>
                  {g.m3u_group_name && (
                    <span className="text-xs text-muted-foreground">was &ldquo;{g.m3u_group_name}&rdquo;</span>
                  )}
                  {g.source_last_seen && (
                    <span className="text-xs text-muted-foreground">
                      · last seen {formatRelativeTime(g.source_last_seen)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowStaleDelete(true)}
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete all stale
            </Button>
          </div>
        </Alert>
      )}

      {/* Fixed Batch Operations Bar */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-50 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="container max-w-screen-xl mx-auto px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
                {selectedIds.size} stream source{selectedIds.size > 1 ? "s" : ""} selected
              </span>
              <div className="flex items-center gap-1">
                <Button variant="outline" size="sm" onClick={() => setSelectedIds(new Set())}>
                  Clear
                </Button>
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
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Groups Table - No card wrapper for more compact look */}
      <div className="border border-border rounded-lg overflow-hidden">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
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
                      Name <SortIcon column="name" />
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-24 text-center cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("matched")}
                  >
                    <div className="flex items-center justify-center">
                      Matched <SortIcon column="matched" />
                    </div>
                  </TableHead>
                  <TableHead
                    className="w-14 cursor-pointer hover:bg-muted/50"
                    onClick={() => handleSort("status")}
                  >
                    <div className="flex items-center">
                      Status <SortIcon column="status" />
                    </div>
                  </TableHead>
                  <TableHead className="w-28 text-right">
                    {sortColumn !== null ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-5 px-1.5 text-xs"
                        onClick={() => { setSortColumn(null); setSortDirection("asc") }}
                        title="Reset to priority order"
                      >
                        <RotateCcw className="h-3 w-3 mr-1" />
                        Priority
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
                {sortedGroups.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      No stream sources match the current filters.
                    </TableCell>
                  </TableRow>
                ) : (
                  <>
                {sortedGroups.map((group) => {
                  return (
                    <React.Fragment key={group.id}>
                      <TableRow
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
                          <div className={`flex items-center justify-center transition-opacity ${
                            isDndActive ? "cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground" : "opacity-0 pointer-events-none"
                          }`}>
                            <GripVertical className="h-4 w-4" />
                          </div>
                        </TableCell>
                        <TableCell>
                          <Checkbox
                            checked={selectedIds.has(group.id)}
                            onCheckedChange={() => toggleSelect(group.id)}
                          />
                        </TableCell>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span>{getDisplayName(group)}</span>
                            {/* Stale-source badge (lylt) */}
                            {staleIds.has(group.id) && (
                              <Badge
                                variant="destructive"
                                className="text-xs"
                                title="This source's M3U group no longer exists in Dispatcharr"
                              >
                                Source missing
                              </Badge>
                            )}
                            {/* Account name badge */}
                            {group.m3u_account_name && (
                              <Badge
                                variant="secondary"
                                className="text-xs"
                                title={`M3U Account: ${group.m3u_account_name}`}
                              >
                                {group.m3u_account_name}
                              </Badge>
                            )}
                            {/* Regex badge */}
                            {(group.custom_regex_teams_enabled ||
                              group.custom_regex_date_enabled ||
                              group.custom_regex_month_enabled ||
                              group.custom_regex_day_enabled ||
                              group.custom_regex_time_enabled ||
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
                                  group.stream_include_regex_enabled && "include",
                                  group.stream_exclude_regex_enabled && "exclude",
                                ].filter(Boolean).join(", ")}`}
                              >
                                Regex
                              </Badge>
                            )}
                            {/* Team Streams badge */}
                            {group.team_streams_enabled && (
                              <Badge
                                variant="secondary"
                                className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-xs"
                                title="Team stream source: team-branded streams match events where that team plays"
                              >
                                Team Streams
                              </Badge>
                            )}
                            {/* EPG Program Matching badge */}
                            {group.epg_match_enabled && (
                              <Badge
                                variant="secondary"
                                className="bg-violet-500/15 text-violet-400 border-violet-500/30 text-xs"
                                title="EPG program matching: static-named linear channels matched to events via Dispatcharr's program guide"
                              >
                                EPG Matched
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                    {/* Matched Column with Progress Bar */}
                    <TableCell className="text-center">
                      {group.team_streams_enabled ? (
                        <span className="text-[0.65rem] text-muted-foreground" title={`Last: ${group.last_refresh ? new Date(group.last_refresh).toLocaleString() : 'Never'}`}>
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
                              <div className="text-muted-foreground">Last: {group.last_refresh ? new Date(group.last_refresh).toLocaleString() : 'Never'}</div>
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
                        disabled={toggleMutation.isPending}
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
                          {previewMutation.isPending &&
                          previewMutation.variables === group.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
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
                          {clearCacheMutation.isPending &&
                          clearCacheMutation.variables === group.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <RotateCcw className="h-4 w-4" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => navigate(`/sources/${group.id}`)}
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setDeleteConfirm(group)}
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                    </React.Fragment>
                  )
                })}
                  </>
                )}
              </TableBody>
            </Table>
          )}
      </div>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
      >
        <DialogContent onClose={() => setDeleteConfirm(null)}>
          <DialogHeader>
            <DialogTitle>Delete Stream Source</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deleteConfirm ? getDisplayName(deleteConfirm) : ''}"? This will
              also delete all {deleteConfirm?.channel_count ?? 0} managed
              channels associated with this stream source.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Clear Cache Confirmation Dialog */}
      <Dialog
        open={clearCacheConfirm !== null}
        onOpenChange={(open) => !open && setClearCacheConfirm(null)}
      >
        <DialogContent onClose={() => setClearCacheConfirm(null)}>
          <DialogHeader>
            <DialogTitle>Clear Match Cache</DialogTitle>
            <DialogDescription>
              Clear the stream match cache for "{clearCacheConfirm ? getDisplayName(clearCacheConfirm) : ''}"?
              This will force re-matching on the next EPG generation run.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearCacheConfirm(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => clearCacheConfirm && handleClearCache(clearCacheConfirm)}
              disabled={clearCacheMutation.isPending}
            >
              {clearCacheMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              Clear Cache
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Clear Cache Confirmation Dialog */}
      <Dialog open={showBulkClearCache} onOpenChange={setShowBulkClearCache}>
        <DialogContent onClose={() => setShowBulkClearCache(false)}>
          <DialogHeader>
            <DialogTitle>Clear Match Cache for {selectedIds.size} Stream Sources</DialogTitle>
            <DialogDescription>
              Clear the stream match cache for {selectedIds.size} selected stream sources?
              This will force re-matching on the next EPG generation run.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBulkClearCache(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleBulkClearCache}
              disabled={clearCachesBulkMutation.isPending}
            >
              {clearCachesBulkMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              Clear Cache for {selectedIds.size} Stream Sources
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Edit Dialog */}
      <Dialog open={showBulkEdit} onOpenChange={(open) => {
        setShowBulkEdit(open)
        if (!open) resetBulkEditForm()
      }}>
        <DialogContent onClose={() => setShowBulkEdit(false)} className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Bulk Edit ({selectedIds.size} stream sources)</DialogTitle>
            <DialogDescription>
              Only checked fields will be updated. Use "Clear" to remove values.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4 px-1 max-h-[60vh] overflow-y-auto">
            {/* Stream Timezone */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={bulkEditStreamTimezoneEnabled}
                  onCheckedChange={(checked) => setBulkEditStreamTimezoneEnabled(!!checked)}
                />
                <span className="text-sm font-medium">Stream Timezone</span>
              </label>
              {bulkEditStreamTimezoneEnabled && (
                <div className="space-y-2 pl-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <Checkbox
                      checked={bulkEditClearStreamTimezone}
                      onCheckedChange={(checked) => {
                        setBulkEditClearStreamTimezone(!!checked)
                        if (checked) {
                          setBulkEditStreamTimezone(null)
                        }
                      }}
                    />
                    <span className="text-sm font-normal">
                      Auto-detect from stream
                    </span>
                  </label>
                  <StreamTimezoneSelector
                    value={bulkEditStreamTimezone}
                    onChange={setBulkEditStreamTimezone}
                    disabled={bulkEditClearStreamTimezone}
                  />
                  <p className="text-xs text-muted-foreground">
                    Timezone used in stream names for date matching
                  </p>
                </div>
              )}
            </div>

            {/* Team Filter */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={bulkEditTeamFilterEnabled}
                  onCheckedChange={(checked) => setBulkEditTeamFilterEnabled(!!checked)}
                />
                <span className="text-sm font-medium">Team Filter</span>
              </label>
              {bulkEditTeamFilterEnabled && (
                <div className="space-y-3 pl-6">
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="bulk-team-filter-action"
                        checked={bulkEditTeamFilterAction === "set"}
                        onChange={() => setBulkEditTeamFilterAction("set")}
                        className="accent-primary"
                      />
                      <span className="text-sm">Set custom filter</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="bulk-team-filter-action"
                        checked={bulkEditTeamFilterAction === "clear"}
                        onChange={() => setBulkEditTeamFilterAction("clear")}
                        className="accent-primary"
                      />
                      <span className="text-sm">Reset to global default</span>
                    </label>
                  </div>

                  {bulkEditTeamFilterAction === "set" && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-4">
                        <Label>Mode:</Label>
                        <div className="flex gap-4">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="radio"
                              name="bulk-team-filter-mode"
                              checked={bulkEditTeamFilterMode === "include"}
                              onChange={() => setBulkEditTeamFilterMode("include")}
                              className="accent-primary"
                            />
                            <span className="text-sm">Include only</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="radio"
                              name="bulk-team-filter-mode"
                              checked={bulkEditTeamFilterMode === "exclude"}
                              onChange={() => setBulkEditTeamFilterMode("exclude")}
                              className="accent-primary"
                            />
                            <span className="text-sm">Exclude</span>
                          </label>
                        </div>
                      </div>
                      <TeamPicker
                        leagues={allLeagueSlugs}
                        selectedTeams={bulkEditTeamFilterTeams}
                        onSelectionChange={setBulkEditTeamFilterTeams}
                        placeholder="Search teams..."
                      />
                      <label className="flex items-center gap-2 cursor-pointer">
                        <Checkbox
                          checked={bulkEditBypassPlayoffs}
                          onCheckedChange={(checked) => setBulkEditBypassPlayoffs(!!checked)}
                        />
                        <span className="text-sm">Include all playoff games</span>
                      </label>
                    </div>
                  )}

                  {bulkEditTeamFilterAction === "clear" && (
                    <p className="text-xs text-muted-foreground">
                      Removes per-source team filter overrides. Stream sources will use the global default filter.
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Team Stream Source */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={bulkEditTeamStreamsEnabled}
                  onCheckedChange={(checked) => setBulkEditTeamStreamsEnabled(!!checked)}
                />
                <span className="text-sm font-medium">Team stream source</span>
              </label>
              {bulkEditTeamStreamsEnabled && (
                <div className="flex items-center gap-3 pl-6">
                  <Switch
                    checked={bulkEditTeamStreams}
                    onCheckedChange={setBulkEditTeamStreams}
                  />
                  <span className="text-sm text-muted-foreground">
                    {bulkEditTeamStreams ? "Enabled — team-branded streams will match events where that team plays" : "Disabled"}
                  </span>
                </div>
              )}
            </div>

            {/* EPG Program Matching */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={bulkEditEPGMatchEnabled}
                  onCheckedChange={(checked) => setBulkEditEPGMatchEnabled(!!checked)}
                />
                <span className="text-sm font-medium">EPG program matching</span>
              </label>
              {bulkEditEPGMatchEnabled && (
                <div className="flex items-center gap-3 pl-6">
                  <Switch
                    checked={bulkEditEPGMatch}
                    onCheckedChange={setBulkEditEPGMatch}
                  />
                  <span className="text-sm text-muted-foreground">
                    {bulkEditEPGMatch ? "Enabled — match static-named linear channels to events via Dispatcharr's program guide (requires the global EPG matching switch)" : "Disabled"}
                  </span>
                </div>
              )}
            </div>

          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBulkEdit(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleBulkEdit}
              disabled={bulkUpdateMutation.isPending || !(bulkEditStreamTimezoneEnabled || bulkEditTeamFilterEnabled || bulkEditTeamStreamsEnabled || bulkEditEPGMatchEnabled)}
            >
              {bulkUpdateMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Apply to {selectedIds.size} groups
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Delete Confirmation Dialog */}
      <Dialog open={showBulkDelete} onOpenChange={setShowBulkDelete}>
        <DialogContent onClose={() => setShowBulkDelete(false)}>
          <DialogHeader>
            <DialogTitle>Delete {selectedIds.size} Stream Sources</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete {selectedIds.size} stream sources? This will
              also delete all managed channels associated with them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBulkDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleBulkDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              Delete {selectedIds.size} Groups
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete-all-stale confirmation */}
      <Dialog open={showStaleDelete} onOpenChange={setShowStaleDelete}>
        <DialogContent onClose={() => setShowStaleDelete(false)}>
          <DialogHeader>
            <DialogTitle>
              Delete {staleGroups.length} stale source{staleGroups.length === 1 ? "" : "s"}
            </DialogTitle>
            <DialogDescription>
              These sources&apos; M3U groups no longer exist in Dispatcharr. Deleting them also
              removes their managed channels. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowStaleDelete(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteAllStale} disabled={deletingStale}>
              {deletingStale && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete all stale
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Stream Preview Modal */}
      <Dialog open={showPreviewModal} onOpenChange={setShowPreviewModal}>
        <DialogContent onClose={() => setShowPreviewModal(false)} className="max-w-4xl max-h-[80vh] overflow-hidden flex flex-col">
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
                            <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {stream.stream_name}
                        </TableCell>
                        <TableCell>
                          {stream.league ? (
                            <Badge variant="secondary">{getLeagueDisplay(stream.league)}</Badge>
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
                                  {new Date(stream.start_time).toLocaleString()}
                                </div>
                              )}
                            </div>
                          ) : stream.exclusion_reason ? (
                            <span className="text-muted-foreground text-xs">
                              {stream.exclusion_reason}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">No match</span>
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
