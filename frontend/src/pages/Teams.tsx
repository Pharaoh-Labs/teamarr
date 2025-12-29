import { useState, useEffect, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import {
  Plus,
  Trash2,
  Pencil,
  Loader2,
  Search,
  Filter,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import { cn } from "@/lib/utils"
import {
  useTeams,
  useUpdateTeam,
  useDeleteTeam,
} from "@/hooks/useTeams"
import { useTemplates } from "@/hooks/useTemplates"
import type { Team } from "@/api/teams"
import { statsApi, type LiveStats } from "@/api/stats"
import { useQuery } from "@tanstack/react-query"

// Sport emoji mapping
const SPORT_EMOJIS: Record<string, string> = {
  basketball: "🏀",
  football: "🏈",
  baseball: "⚾",
  hockey: "🏒",
  soccer: "⚽",
  mma: "🥊",
  boxing: "🥊",
  default: "🏆",
}

function getSportEmoji(sport: string): string {
  return SPORT_EMOJIS[sport.toLowerCase()] || SPORT_EMOJIS.default
}

// Fetch leagues for logo lookup
async function fetchLeagues(): Promise<{ slug: string; logo_url: string | null }[]> {
  const response = await fetch("/api/v1/cache/leagues")
  if (!response.ok) return []
  const data = await response.json()
  return data.leagues || []
}

type ActiveFilter = "all" | "active" | "inactive"

interface TeamUpdate {
  team_name?: string
  team_abbrev?: string | null
  team_logo_url?: string | null
  channel_id?: string
  channel_logo_url?: string | null
  template_id?: number | null
  active?: boolean
}

interface EditTeamDialogProps {
  team: Team
  templates: Array<{ id: number; name: string }>
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (data: TeamUpdate) => Promise<void>
  isSaving: boolean
}

function EditTeamDialog({ team, templates, open, onOpenChange, onSave, isSaving }: EditTeamDialogProps) {
  const [formData, setFormData] = useState<TeamUpdate>({
    team_name: team.team_name,
    team_abbrev: team.team_abbrev,
    team_logo_url: team.team_logo_url,
    channel_id: team.channel_id,
    channel_logo_url: team.channel_logo_url,
    template_id: team.template_id,
    active: team.active,
  })

  const handleSubmit = async () => {
    if (!formData.team_name?.trim()) {
      toast.error("Team name is required")
      return
    }
    if (!formData.channel_id?.trim()) {
      toast.error("Channel ID is required")
      return
    }
    await onSave(formData)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" onClose={() => onOpenChange(false)}>
        <DialogHeader>
          <DialogTitle>Edit Team</DialogTitle>
          <DialogDescription>Update team channel settings.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="team_name">Team Name</Label>
              <Input
                id="team_name"
                value={formData.team_name ?? ""}
                onChange={(e) => setFormData({ ...formData, team_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="team_abbrev">Abbreviation</Label>
              <Input
                id="team_abbrev"
                value={formData.team_abbrev ?? ""}
                onChange={(e) => setFormData({ ...formData, team_abbrev: e.target.value || null })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="channel_id">Channel ID</Label>
            <Input
              id="channel_id"
              value={formData.channel_id ?? ""}
              onChange={(e) => setFormData({ ...formData, channel_id: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">Unique identifier for XMLTV output</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="template_id">Template</Label>
            <Select
              id="template_id"
              value={formData.template_id?.toString() ?? ""}
              onChange={(e) => setFormData({ ...formData, template_id: e.target.value ? parseInt(e.target.value) : null })}
            >
              <option value="">Default Template</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id.toString()}>
                  {template.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={formData.active ?? true}
              onCheckedChange={(checked) => setFormData({ ...formData, active: checked })}
            />
            <Label className="font-normal">Active</Label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSaving}>
            {isSaving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Update
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Teams() {
  const navigate = useNavigate()
  const { data: teams, isLoading, error, refetch } = useTeams()
  const { data: templates } = useTemplates()
  const { data: cachedLeagues } = useQuery({ queryKey: ["leagues"], queryFn: fetchLeagues })
  const { data: liveStats } = useQuery({
    queryKey: ["stats", "live", "team"],
    queryFn: () => statsApi.getLiveStats("team"),
    refetchInterval: 60000, // Refresh every minute
  })

  // Create league logo lookup map
  const leagueLogos = useMemo(() => {
    const map: Record<string, string> = {}
    if (cachedLeagues) {
      for (const league of cachedLeagues) {
        if (league.logo_url) {
          map[league.slug] = league.logo_url
        }
      }
    }
    return map
  }, [cachedLeagues])
  const updateMutation = useUpdateTeam()
  const deleteMutation = useDeleteTeam()

  // Filter state
  const [searchFilter, setSearchFilter] = useState("")
  const [leagueFilter, setLeagueFilter] = useState<string>("")
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("all")
  const [showFilters, setShowFilters] = useState(false)

  // Bulk selection state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [lastClickedIndex, setLastClickedIndex] = useState<number | null>(null)
  const [bulkTemplateId, setBulkTemplateId] = useState<number | null>(null)
  const [showBulkTemplate, setShowBulkTemplate] = useState(false)
  const [showBulkDelete, setShowBulkDelete] = useState(false)

  // Edit dialog state
  const [showDialog, setShowDialog] = useState(false)
  const [editingTeam, setEditingTeam] = useState<Team | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<Team | null>(null)

  // Get unique leagues from teams (using primary_league)
  const leagues = useMemo(() => {
    if (!teams) return []
    const uniqueLeagues = [...new Set(teams.map((t) => t.primary_league))]
    return uniqueLeagues.sort()
  }, [teams])

  // Filter templates to only show team templates
  const teamTemplates = useMemo(() => {
    return templates?.filter((t) => t.template_type === "team") ?? []
  }, [templates])

  // Calculate team stats for tiles
  const teamStats = useMemo(() => {
    if (!teams) return { total: 0, enabled: 0, byLeague: {} as Record<string, { total: number; enabled: number }> }

    const byLeague: Record<string, { total: number; enabled: number }> = {}

    for (const team of teams) {
      // Count by primary league
      if (!byLeague[team.primary_league]) {
        byLeague[team.primary_league] = { total: 0, enabled: 0 }
      }
      byLeague[team.primary_league].total++
      if (team.active) {
        byLeague[team.primary_league].enabled++
      }
    }

    return {
      total: teams.length,
      enabled: teams.filter((t) => t.active).length,
      byLeague,
    }
  }, [teams])

  // Filter teams
  const filteredTeams = useMemo(() => {
    if (!teams) return []
    return teams.filter((team) => {
      // Search filter
      if (searchFilter) {
        const q = searchFilter.toLowerCase()
        const matches =
          team.team_name.toLowerCase().includes(q) ||
          team.team_abbrev?.toLowerCase().includes(q) ||
          team.channel_id.toLowerCase().includes(q) ||
          team.primary_league.toLowerCase().includes(q) ||
          team.leagues.some((l) => l.toLowerCase().includes(q))
        if (!matches) return false
      }

      // League filter - match if any of the team's leagues match
      if (leagueFilter && !team.leagues.includes(leagueFilter)) return false

      // Active filter
      if (activeFilter === "active" && !team.active) return false
      if (activeFilter === "inactive" && team.active) return false

      return true
    })
  }, [teams, searchFilter, leagueFilter, activeFilter])

  // Clear selection when filters change
  useEffect(() => {
    setSelectedIds(new Set())
    setLastClickedIndex(null)
  }, [searchFilter, leagueFilter, activeFilter])

  const openEdit = (team: Team) => {
    setEditingTeam(team)
    setShowDialog(true)
  }

  const handleDelete = async () => {
    if (!deleteConfirm) return

    try {
      await deleteMutation.mutateAsync(deleteConfirm.id)
      toast.success(`Deleted team "${deleteConfirm.team_name}"`)
      setDeleteConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete team")
    }
  }

  const handleToggleActive = async (team: Team) => {
    try {
      await updateMutation.mutateAsync({
        teamId: team.id,
        data: { active: !team.active },
      })
      toast.success(`${team.active ? "Disabled" : "Enabled"} team "${team.team_name}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to toggle team status")
    }
  }

  // Bulk actions
  const toggleSelectAll = () => {
    if (selectedIds.size === filteredTeams.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredTeams.map((t) => t.id)))
    }
  }

  const toggleSelect = (id: number, index: number, shiftKey: boolean) => {
    if (shiftKey && lastClickedIndex !== null) {
      // Shift-click: select range
      const start = Math.min(lastClickedIndex, index)
      const end = Math.max(lastClickedIndex, index)

      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (let i = start; i <= end; i++) {
          next.add(filteredTeams[i].id)
        }
        return next
      })
    } else {
      // Regular click: toggle single item
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
    setLastClickedIndex(index)
  }

  const handleBulkToggleActive = async (active: boolean) => {
    const ids = Array.from(selectedIds)
    let succeeded = 0
    for (const id of ids) {
      try {
        await updateMutation.mutateAsync({ teamId: id, data: { active } })
        succeeded++
      } catch {
        // Continue with others
      }
    }
    toast.success(`${active ? "Enabled" : "Disabled"} ${succeeded} teams`)
    setSelectedIds(new Set())
  }

  const handleBulkAssignTemplate = async () => {
    const ids = Array.from(selectedIds)
    let succeeded = 0
    for (const id of ids) {
      try {
        await updateMutation.mutateAsync({ teamId: id, data: { template_id: bulkTemplateId } })
        succeeded++
      } catch {
        // Continue with others
      }
    }
    toast.success(`Assigned template to ${succeeded} teams`)
    setSelectedIds(new Set())
    setShowBulkTemplate(false)
    setBulkTemplateId(null)
  }

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds)
    let succeeded = 0
    for (const id of ids) {
      try {
        await deleteMutation.mutateAsync(id)
        succeeded++
      } catch {
        // Continue with others
      }
    }
    toast.success(`Deleted ${succeeded} teams`)
    setSelectedIds(new Set())
    setShowBulkDelete(false)
  }

  const hasActiveFilters = searchFilter || leagueFilter || activeFilter !== "all"

  const clearFilters = () => {
    setSearchFilter("")
    setLeagueFilter("")
    setActiveFilter("all")
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Teams</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">Error loading teams: {error.message}</p>
            <Button className="mt-4" onClick={() => refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Teams</h1>
          <p className="text-muted-foreground">Team-based EPG channel configurations</p>
        </div>
        <Button onClick={() => navigate("/teams/import")}>
          <Plus className="h-4 w-4 mr-1.5" />
          Import Teams
        </Button>
      </div>

      {/* Stats Tiles */}
      {teams && teams.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {/* Configured */}
          <div className="group relative">
            <Card className="p-3 cursor-help">
              <div className="text-2xl font-bold">{teamStats.total}</div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide">Configured</div>
            </Card>
            <div className="absolute left-0 top-full mt-1 z-50 hidden group-hover:block">
              <Card className="p-3 shadow-lg min-w-[160px]">
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 pb-1 border-b">
                  By League
                </div>
                <div className="space-y-1">
                  {Object.entries(teamStats.byLeague)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([league, counts]) => (
                      <div key={league} className="flex justify-between text-sm">
                        <span className="text-muted-foreground">{league.toUpperCase()}</span>
                        <span className="font-medium">{counts.total}</span>
                      </div>
                    ))}
                </div>
              </Card>
            </div>
          </div>

          {/* Enabled */}
          <div className="group relative">
            <Card className="p-3 cursor-help">
              <div className="text-2xl font-bold">{teamStats.enabled}</div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide">Enabled</div>
            </Card>
            <div className="absolute left-0 top-full mt-1 z-50 hidden group-hover:block">
              <Card className="p-3 shadow-lg min-w-[160px]">
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 pb-1 border-b">
                  By League
                </div>
                <div className="space-y-1">
                  {Object.entries(teamStats.byLeague)
                    .filter(([, counts]) => counts.enabled > 0)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([league, counts]) => (
                      <div key={league} className="flex justify-between text-sm">
                        <span className="text-muted-foreground">{league.toUpperCase()}</span>
                        <span className="font-medium">{counts.enabled}</span>
                      </div>
                    ))}
                </div>
              </Card>
            </div>
          </div>

          {/* Games Today */}
          <div className="group relative">
            <Card className="p-3 cursor-help">
              <div className={cn(
                "text-2xl font-bold",
                liveStats?.team.games_today ? "" : "text-muted-foreground"
              )}>
                {liveStats?.team.games_today ?? "--"}
              </div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide">Games Today</div>
            </Card>
            {liveStats?.team.by_league && liveStats.team.by_league.length > 0 && (
              <div className="absolute left-0 top-full mt-1 z-50 hidden group-hover:block">
                <Card className="p-3 shadow-lg min-w-[120px]">
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 pb-1 border-b">
                    By League
                  </div>
                  <div className="space-y-1">
                    {liveStats.team.by_league.map((item) => (
                      <div key={item.league} className="flex justify-between text-sm gap-3">
                        <span className="text-muted-foreground">{item.league}</span>
                        <span className="font-medium">{item.count}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            )}
          </div>

          {/* Live Now */}
          <Card className="p-3">
            <div className={cn(
              "text-2xl font-bold",
              liveStats?.team.live_now ? "text-green-600" : "text-muted-foreground"
            )}>
              {liveStats?.team.live_now ?? "--"}
            </div>
            <div className="text-xs text-muted-foreground uppercase tracking-wide">Live Now</div>
          </Card>
        </div>
      )}

      {/* Filters and View Toggle */}
      <Card>
        <CardContent className="py-3">
          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Search teams..."
                className="pl-10"
              />
            </div>

            {/* Filter toggle */}
            <Button
              variant={showFilters ? "secondary" : "outline"}
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
            >
              <Filter className="h-4 w-4 mr-1" />
              Filters
              {hasActiveFilters && (
                <Badge variant="secondary" className="ml-1 h-5 w-5 p-0 justify-center">
                  {(leagueFilter ? 1 : 0) + (activeFilter !== "all" ? 1 : 0)}
                </Badge>
              )}
            </Button>

            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters}>
                <X className="h-4 w-4 mr-1" />
                Clear
              </Button>
            )}
          </div>

          {/* Expanded filters */}
          {showFilters && (
            <div className="flex items-center gap-3 mt-3 pt-3 border-t">
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">League</Label>
                <Select
                  value={leagueFilter}
                  onChange={(e) => setLeagueFilter(e.target.value)}
                  className="w-40"
                >
                  <option value="">All leagues</option>
                  {leagues.map((league) => (
                    <option key={league} value={league}>
                      {league}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Status</Label>
                <Select
                  value={activeFilter}
                  onChange={(e) => setActiveFilter(e.target.value as ActiveFilter)}
                  className="w-32"
                >
                  <option value="all">All</option>
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </Select>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bulk Actions Bar - always visible */}
      <Card className={cn(
        "transition-colors",
        selectedIds.size > 0 ? "bg-primary/5 border-primary/20" : "bg-muted/30"
      )}>
        <CardContent className="py-3">
          <div className="flex items-center gap-3">
            <span className={cn(
              "text-sm font-medium",
              selectedIds.size === 0 && "text-muted-foreground"
            )}>
              {selectedIds.size > 0
                ? `${selectedIds.size} team${selectedIds.size !== 1 ? "s" : ""} selected`
                : "No teams selected"}
            </span>
            <div className="flex-1" />
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkToggleActive(true)}
              disabled={selectedIds.size === 0}
            >
              Enable
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkToggleActive(false)}
              disabled={selectedIds.size === 0}
            >
              Disable
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowBulkTemplate(true)}
              disabled={selectedIds.size === 0}
            >
              Assign Template
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowBulkDelete(true)}
              disabled={selectedIds.size === 0}
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
            {selectedIds.size > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setSelectedIds(new Set())}>
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Teams List */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>
            Teams ({filteredTeams.length}
            {filteredTeams.length !== teams?.length && ` of ${teams?.length}`})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredTeams.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {teams?.length === 0
                ? "No teams configured. Add a team to generate team-based EPG."
                : "No teams match the current filters."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={
                        selectedIds.size === filteredTeams.length && filteredTeams.length > 0
                      }
                      onCheckedChange={toggleSelectAll}
                    />
                  </TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead className="w-16">League</TableHead>
                  <TableHead className="w-14">Sport</TableHead>
                  <TableHead>Channel ID</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead className="w-16">Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredTeams.map((team, index) => (
                  <TableRow
                    key={team.id}
                    className={cn(selectedIds.has(team.id) && "bg-muted/50")}
                  >
                    <TableCell>
                      <Checkbox
                        checked={selectedIds.has(team.id)}
                        onClick={(e) => toggleSelect(team.id, index, e.shiftKey)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {team.team_logo_url && (
                          <img
                            src={team.team_logo_url}
                            alt=""
                            className="h-8 w-8 object-contain"
                          />
                        )}
                        <div>
                          <div className="font-medium">{team.team_name}</div>
                          {team.team_abbrev && (
                            <div className="text-xs text-muted-foreground">{team.team_abbrev}</div>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {(() => {
                        const hasMultiLeague = team.leagues.length > 1

                        const leagueDisplay = (
                          <div
                            className={cn("relative inline-block", hasMultiLeague && "cursor-help")}
                          >
                            {leagueLogos[team.primary_league] ? (
                              <img
                                src={leagueLogos[team.primary_league]}
                                alt={team.primary_league.toUpperCase()}
                                title={team.primary_league.toUpperCase()}
                                className="h-7 w-auto object-contain"
                              />
                            ) : (
                              <Badge variant="secondary">{team.primary_league}</Badge>
                            )}
                            {/* Multi-league badge */}
                            {hasMultiLeague && (
                              <span className="absolute -bottom-1 -right-1 bg-primary text-primary-foreground text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center border border-background">
                                +{team.leagues.length - 1}
                              </span>
                            )}
                          </div>
                        )

                        if (hasMultiLeague) {
                          return (
                            <RichTooltip
                              title="Competitions"
                              side="bottom"
                              align="start"
                              content={
                                <div className="space-y-1.5">
                                  {team.leagues.map((leagueSlug) => (
                                    <div key={leagueSlug} className="flex items-center gap-2 text-sm">
                                      {leagueLogos[leagueSlug] && (
                                        <img
                                          src={leagueLogos[leagueSlug]}
                                          alt=""
                                          className="h-5 w-5 object-contain"
                                        />
                                      )}
                                      <span className={leagueSlug === team.primary_league ? "font-medium text-foreground" : "text-muted-foreground"}>
                                        {leagueSlug.toUpperCase()}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              }
                            >
                              {leagueDisplay}
                            </RichTooltip>
                          )
                        }

                        return leagueDisplay
                      })()}
                    </TableCell>
                    <TableCell>
                      <span className="text-xl" title={team.sport}>
                        {getSportEmoji(team.sport)}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-sm">{team.channel_id}</TableCell>
                    <TableCell>
                      {team.template_id ? (
                        <span className="text-muted-foreground">
                          {templates?.find((t) => t.id === team.template_id)?.name ??
                            `#${team.template_id}`}
                        </span>
                      ) : (
                        <span className="text-muted-foreground italic">Default</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={team.active}
                        onCheckedChange={() => handleToggleActive(team)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => openEdit(team)}
                          title="Edit"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => setDeleteConfirm(team)}
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Edit Team Dialog */}
      {editingTeam && (
        <EditTeamDialog
          team={editingTeam}
          templates={teamTemplates}
          open={showDialog}
          onOpenChange={(open) => {
            if (!open) {
              setShowDialog(false)
              setEditingTeam(null)
            }
          }}
          onSave={async (data) => {
            await updateMutation.mutateAsync({ teamId: editingTeam.id, data })
            toast.success(`Updated team "${data.team_name || editingTeam.team_name}"`)
            setShowDialog(false)
            setEditingTeam(null)
          }}
          isSaving={updateMutation.isPending}
        />
      )}

      {/* Delete Confirmation */}
      <Dialog open={deleteConfirm !== null} onOpenChange={(open) => !open && setDeleteConfirm(null)}>
        <DialogContent onClose={() => setDeleteConfirm(null)}>
          <DialogHeader>
            <DialogTitle>Delete Team</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deleteConfirm?.team_name}"? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Assign Template Dialog */}
      <Dialog open={showBulkTemplate} onOpenChange={setShowBulkTemplate}>
        <DialogContent onClose={() => setShowBulkTemplate(false)}>
          <DialogHeader>
            <DialogTitle>Assign Template</DialogTitle>
            <DialogDescription>
              Assign a template to {selectedIds.size} selected team{selectedIds.size !== 1 && "s"}.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Select
              value={bulkTemplateId?.toString() ?? ""}
              onChange={(e) =>
                setBulkTemplateId(e.target.value ? parseInt(e.target.value) : null)
              }
            >
              <option value="">Default Template</option>
              {teamTemplates.map((template) => (
                <option key={template.id} value={template.id.toString()}>
                  {template.name}
                </option>
              ))}
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBulkTemplate(false)}>
              Cancel
            </Button>
            <Button onClick={handleBulkAssignTemplate} disabled={updateMutation.isPending}>
              {updateMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Assign
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Delete Confirmation */}
      <Dialog open={showBulkDelete} onOpenChange={setShowBulkDelete}>
        <DialogContent onClose={() => setShowBulkDelete(false)}>
          <DialogHeader>
            <DialogTitle>Delete Teams</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete {selectedIds.size} team{selectedIds.size !== 1 && "s"}?
              This cannot be undone.
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
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete {selectedIds.size} Team{selectedIds.size !== 1 && "s"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
