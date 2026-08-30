import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { LoaderCircle, Plus, Star, Trash2, WandSparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { RadioCards } from "@/components/ui/radio-cards"
import { Select } from "@/components/ui/select"
import { useSports } from "@/hooks/useSports"
import { getSportDisplayName } from "@/lib/utils"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  HierarchicalSortable,
  type HierarchicalItem,
  type GroupedItem,
} from "@/components/ui/hierarchical-sortable"
import { TeamPicker } from "@/components/TeamPicker"
import {
  useSortPriorities,
  useReorderSortPriorities,
  useAutoPopulateSortPriorities,
  usePriorityTeams,
  useAddPriorityTeam,
  useDeletePriorityTeam,
  useUpdatePriorityTeamScope,
} from "@/hooks/useSortPriorities"
import type {
  PriorityTeam,
  PriorityTeamScope,
  SortPriorityReorderItem,
} from "@/api/sortPriorities"
import type { TeamFilterEntry } from "@/api/types"
import { getTeamPickerLeagues } from "@/api/teams"

interface SortPriorityManagerProps {
  showWhenSortBy?: string
  currentSortBy: string
}

const SCOPE_OPTIONS: { value: PriorityTeamScope; label: string; hint: string }[] = [
  { value: "league", label: "Top of its league", hint: "First among its league's games; sport and league order untouched." },
  { value: "sport", label: "Top of its sport", hint: "First among every league in its sport." },
  { value: "all", label: "Top of everything", hint: "Ahead of every sport and league." },
]

/**
 * Priority Teams — a team-level tier that floats a followed team's channels to
 * the top of a scope: its league (default), its sport, or everything. Pinned
 * blocks partition the lineup after sorting, so the float only moves a team
 * relative to other channels in the same block. One row per team with a scope
 * select; the TeamPicker (single-select, always empty) is the "add" control.
 */
export function PriorityTeamsCard() {
  const { data: priorityTeams, isLoading } = usePriorityTeams()
  const addMutation = useAddPriorityTeam()
  const deleteMutation = useDeletePriorityTeam()
  const scopeMutation = useUpdatePriorityTeamScope()
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports

  // Offer teams from every league that has cached teams.
  const { data: leagueData } = useQuery({
    queryKey: ["teamPickerLeagues"],
    queryFn: getTeamPickerLeagues,
    staleTime: 5 * 60 * 1000,
  })
  const leagues = useMemo(
    () => (leagueData?.leagues ?? []).filter((l) => l.team_count > 0).map((l) => l.slug),
    [leagueData],
  )

  const [addOpen, setAddOpen] = useState(false)
  const [pick, setPick] = useState<TeamFilterEntry[]>([])
  const [pickScope, setPickScope] = useState<PriorityTeamScope>("league")

  const onAdd = async () => {
    const team = pick[0]
    if (!team) return
    try {
      await addMutation.mutateAsync({ team, scope: pickScope })
      toast.success(`${team.name} added — re-grid queued for the next generation`)
      setPick([])
      setPickScope("league")
      setAddOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add priority team")
    }
  }

  const onScope = async (id: number, scope: PriorityTeamScope) => {
    try {
      await scopeMutation.mutateAsync({ id, scope })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update priority team")
    }
  }

  const onRemove = async (t: PriorityTeam) => {
    try {
      await deleteMutation.mutateAsync(t.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove priority team")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Star className="h-4 w-4" /> Priority Teams
            </CardTitle>
            <CardDescription>
              Float a team&apos;s games to the top of its league, its sport, or everything.
              A team floats up wherever it plays (league and cup). Inside a pinned block the
              float applies within that block. Ordering only — unrelated to the Teams page
              or EPG.
            </CardDescription>
          </div>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> Add team
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <LoaderCircle className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (priorityTeams ?? []).length > 0 ? (
          <div className="border rounded-md divide-y">
            {(priorityTeams ?? []).map((t) => (
              <div key={t.id} className="flex items-center gap-3 px-3 py-2">
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{t.team_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {getSportDisplayName(t.sport, sportsMap)}
                    {t.league ? ` · ${t.league}` : ""}
                  </div>
                </div>
                <Select
                  value={t.scope}
                  onChange={(e) => onScope(t.id, e.target.value as PriorityTeamScope)}
                  className="w-44 h-8 text-sm"
                  aria-label="Float scope"
                  title={SCOPE_OPTIONS.find((o) => o.value === t.scope)?.hint}
                >
                  {SCOPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => onRemove(t)}
                  disabled={deleteMutation.isPending}
                  aria-label="Remove priority team"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground py-1">
            No priority teams. Games number in Sport &amp; League order, then by start time.
          </p>
        )}
      </CardContent>

      <Dialog
        open={addOpen}
        onOpenChange={(v) => {
          if (!v) {
            setPick([])
            setPickScope("league")
          }
          setAddOpen(v)
        }}
      >
        <DialogContent className="max-w-lg" onClose={() => setAddOpen(false)}>
          <DialogHeader>
            <DialogTitle>Add priority team</DialogTitle>
            <DialogDescription>
              Pick a team and how far its games float in the lineup.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <RadioCards
              name="priority-scope"
              value={pickScope}
              onChange={(v) => setPickScope(v as PriorityTeamScope)}
              options={SCOPE_OPTIONS.map((o) => ({
                value: o.value,
                label: o.label,
                description: o.hint,
              }))}
            />
            <div className="space-y-2">
              <Label>Team</Label>
              <TeamPicker
                leagues={leagues}
                selectedTeams={pick}
                onSelectionChange={(t) => setPick(t.slice(-1))}
                placeholder="Pick a team…"
                singleSelect
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button onClick={onAdd} disabled={pick.length !== 1 || addMutation.isPending}>
              {addMutation.isPending ? "Adding…" : "Add team"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

/** Sport & League Order — the lineup order used inside every pinned block and
 * in Everything Else. Higher = lower channel numbers. */
export function SportLeagueOrderCard({ showWhenSortBy = "sport_league_time", currentSortBy }: SortPriorityManagerProps) {
  const { data: priorities, isLoading, refetch } = useSortPriorities()
  const reorderMutation = useReorderSortPriorities()
  const autoPopulateMutation = useAutoPopulateSortPriorities()

  // Transform priorities to HierarchicalItem format
  // First, build a map of sport codes to display names from sport-level entries
  const sportDisplayNames = useMemo(() => {
    if (!priorities) return new Map<string, string>()
    const names = new Map<string, string>()
    for (const p of priorities) {
      // Sport-level entries (league_code is null) have the sport display name
      if (p.league_code === null && p.display_name) {
        names.set(p.sport, p.display_name)
      }
    }
    return names
  }, [priorities])

  const items: HierarchicalItem[] = useMemo(() => {
    if (!priorities) return []
    return priorities.map(p => ({
      id: p.id,
      group: p.sport,
      groupLabel: sportDisplayNames.get(p.sport) || p.sport,
      child: p.league_code,
      sortPriority: p.sort_priority,
      label: p.display_name || p.league_code || p.sport,
      metadata: {
        channel_count: p.channel_count,
      },
    }))
  }, [priorities, sportDisplayNames])

  // Don't render if sort_by doesn't match (after hooks — rules of hooks)
  if (currentSortBy !== showWhenSortBy) {
    return null
  }

  const handleReorder = async (newOrder: Array<{ group: string; child: string | null; priority: number }>) => {
    const reorderData: SortPriorityReorderItem[] = newOrder.map(item => ({
      sport: item.group,
      league_code: item.child,
      priority: item.priority,
    }))

    try {
      await reorderMutation.mutateAsync(reorderData)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reorder")
      refetch()
    }
  }

  const handleAutoPopulate = async () => {
    try {
      const result = await autoPopulateMutation.mutateAsync()
      if (result.added > 0) {
        toast.success(`Added ${result.added} sport/league priorities`)
      } else {
        toast.info(result.message)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to auto-populate")
    }
  }

  // Render extra content for group headers (league count + channel count)
  const renderGroupExtra = (group: GroupedItem) => {
    const channelCount = group.children.reduce((sum, child) => {
      const count = (child.metadata?.channel_count as number) || 0
      return sum + count
    }, (group.groupItem?.metadata?.channel_count as number) || 0)

    return (
      <>
        <span className="text-xs text-muted-foreground">
          {group.children.length} league{group.children.length !== 1 ? "s" : ""}
        </span>
        {channelCount > 0 && (
          <span className="text-xs text-muted-foreground">
            ({channelCount} ch)
          </span>
        )}
      </>
    )
  }

  // Render extra content for child items (channel count)
  const renderChildExtra = (item: HierarchicalItem) => {
    const channelCount = item.metadata?.channel_count as number | undefined
    if (channelCount === null || channelCount === undefined) return null
    return (
      <span className="text-xs text-muted-foreground">
        {channelCount} ch
      </span>
    )
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    )
  }

  return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">Sport &amp; League Order</CardTitle>
              <CardDescription>
                The order sports and leagues take inside Everything Else and inside every
                pinned block: higher in this list = lower channel numbers. Games within a
                league sort by start time. Drag sports to reorder; expand to reorder leagues
                within each sport. Unlisted sports/leagues go last.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleAutoPopulate}
              disabled={autoPopulateMutation.isPending}
            >
              {autoPopulateMutation.isPending ? (
                <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <WandSparkles className="h-4 w-4 mr-1" />
              )}
              Auto-populate
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <HierarchicalSortable
            items={items}
            onReorder={handleReorder}
            renderGroupExtra={renderGroupExtra}
            renderChildExtra={renderChildExtra}
            emptyMessage="No sort priorities configured. Click 'Auto-populate' to add all active sports/leagues."
          />
        </CardContent>
      </Card>
  )
}
