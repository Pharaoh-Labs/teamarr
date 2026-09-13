import { useState } from "react"
import { toast } from "sonner"
import { Trash2, Radio, Plus, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { ResponsiveTable } from "@/components/ui/responsive-table"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Select } from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  useBroadcasters,
  useRsnCatalog,
  useCreateBroadcaster,
  useUpdateBroadcaster,
  useDeleteBroadcaster,
  type BroadcasterMapping,
} from "@/api/broadcasters"
import { TeamPicker } from "@/components/TeamPicker"
import { LeaguePicker } from "@/components/LeaguePicker"
import type { TeamFilterEntry } from "@/api/types"

/**
 * Broadcasters / RSN Mappings section.
 * Allows users to map custom stream names, regexes, or tvg-ids to specific teams
 * (e.g. MASN -> Orioles) and inspect the built-in 1:1 RSN catalog.
 */
export function BroadcastersSection() {
  const broadcastersQuery = useBroadcasters()
  const rsnCatalogQuery = useRsnCatalog("mlb")
  const createMutation = useCreateBroadcaster()
  const updateMutation = useUpdateBroadcaster()
  const deleteMutation = useDeleteBroadcaster()

  const mappings = broadcastersQuery.data || []
  const catalog = rsnCatalogQuery.data || []

  const [showDialog, setShowDialog] = useState(false)
  const [showCatalog, setShowCatalog] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; name: string } | null>(null)

  const [form, setForm] = useState<{
    name: string
    pattern: string
    pattern_type: "regex" | "exact" | "tvg_id" | "channel_id"
    league: string
    team_id: string
    team_name: string
    is_active: boolean
  }>({
    name: "",
    pattern: "",
    pattern_type: "regex",
    league: "mlb",
    team_id: "",
    team_name: "",
    is_active: true,
  })
  const [selectedTeams, setSelectedTeams] = useState<TeamFilterEntry[]>([])

  const resetForm = () => {
    setForm({
      name: "",
      pattern: "",
      pattern_type: "regex",
      league: "mlb",
      team_id: "",
      team_name: "",
      is_active: true,
    })
    setSelectedTeams([])
  }

  const handleTeamSelect = (teams: TeamFilterEntry[]) => {
    setSelectedTeams(teams)
    const team = teams[0]
    if (team) {
      setForm((f) => ({
        ...f,
        team_id: team.team_id,
        team_name: team.name || "",
      }))
    } else {
      setForm((f) => ({ ...f, team_id: "", team_name: "" }))
    }
  }

  const handleCreate = async () => {
    if (!form.name.trim()) {
      toast.error("Please enter a mapping name")
      return
    }
    if (!form.pattern.trim()) {
      toast.error("Please enter a match pattern")
      return
    }
    if (!form.team_id) {
      toast.error("Please select a target team")
      return
    }

    try {
      await createMutation.mutateAsync({
        name: form.name.trim(),
        pattern: form.pattern.trim(),
        pattern_type: form.pattern_type,
        league: form.league,
        team_id: form.team_id,
        team_name: form.team_name || null,
        is_active: form.is_active,
      })
      toast.success("Broadcaster mapping created")
      setShowDialog(false)
      resetForm()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create mapping")
    }
  }

  const handleDelete = async () => {
    if (!deleteConfirm) return
    try {
      await deleteMutation.mutateAsync(deleteConfirm.id)
      toast.success("Broadcaster mapping deleted")
      setDeleteConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete mapping")
    }
  }

  const handleToggleActive = async (mapping: BroadcasterMapping) => {
    try {
      await updateMutation.mutateAsync({
        id: mapping.id,
        data: { is_active: !mapping.is_active },
      })
      toast.success(`Mapping ${mapping.is_active ? "disabled" : "enabled"}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update mapping")
    }
  }

  return (
    <>
      <CollapsibleSection
        title="Broadcasters & RSN Feeds"
        count={
          <Badge variant="secondary" className="gap-1 font-mono">
            <Radio className="h-3 w-3" />
            {mappings.length} Custom
          </Badge>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowCatalog(!showCatalog)}
            >
              <Info className="h-4 w-4 mr-1.5" />
              {showCatalog ? "Hide Built-in Catalog" : "View Built-in RSNs"}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                resetForm()
                setShowDialog(true)
              }}
            >
              <Plus className="h-4 w-4 mr-1.5" />
              Add Mapping
            </Button>
          </div>
        }
      >
        {/* Built-in Catalog Reference Drawer */}
        {showCatalog && (
          <div className="mb-4 rounded-md border border-muted bg-muted/30 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Pre-seeded 1:1 MLB RSN Catalog ({catalog.length} Networks)
              </h4>
              <span className="text-xs text-muted-foreground">
                Auto-resolves Home/Away feeds when unambiguous
              </span>
            </div>
            <div className="max-h-48 overflow-y-auto divide-y divide-border/40 text-xs">
              {catalog.map((entry) => (
                <div
                  key={entry.network_name}
                  className="py-1.5 flex items-center justify-between gap-2"
                >
                  <div>
                    <span className="font-medium">{entry.network_name}</span>
                    {entry.is_ambiguous && (
                      <Badge variant="outline" className="ml-2 text-[10px] text-amber-500">
                        Multi-Team (No Auto-Resolve)
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground font-mono text-[11px]">
                      {entry.patterns[0]}
                    </span>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {entry.team_abbreviation}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Custom Mappings Table */}
        {mappings.length === 0 ? (
          <div className="text-center py-6 text-sm text-muted-foreground">
            No custom broadcaster mappings defined. Built-in 1:1 RSNs will auto-resolve
            unambiguous feeds. Click <strong>Add Mapping</strong> to map custom stream patterns
            or multi-team channels like MASN.
          </div>
        ) : (
          <ResponsiveTable
            rows={mappings}
            keyExtractor={(m) => m.id}
            columns={[
              {
                key: "name",
                header: "Mapping Name",
                cell: (m) => (
                  <div>
                    <div className="font-medium text-sm">{m.name}</div>
                    <div className="text-xs text-muted-foreground font-mono truncate max-w-xs">
                      {m.pattern}
                    </div>
                  </div>
                ),
              },
              {
                key: "pattern_type",
                header: "Match Type",
                headerClassName: "w-[120px]",
                cell: (m) => (
                  <Badge variant="outline" className="capitalize text-xs">
                    {m.pattern_type}
                  </Badge>
                ),
              },
              {
                key: "team",
                header: "Target Team",
                headerClassName: "w-[200px]",
                cell: (m) => (
                  <div className="flex items-center gap-1.5">
                    <Badge variant="secondary" className="font-mono">
                      {m.team_id}
                    </Badge>
                    {m.team_name && (
                      <span className="text-xs text-muted-foreground truncate max-w-[120px]">
                        {m.team_name}
                      </span>
                    )}
                  </div>
                ),
              },
              {
                key: "league",
                header: "League",
                headerClassName: "w-[90px]",
                cell: (m) => <Badge variant="secondary">{m.league.toUpperCase()}</Badge>,
              },
              {
                key: "status",
                header: "Status",
                headerClassName: "w-[90px]",
                cell: (m) => (
                  <Switch
                    checked={m.is_active}
                    onCheckedChange={() => handleToggleActive(m)}
                    aria-label="Toggle active status"
                  />
                ),
              },
              {
                key: "actions",
                header: "Actions",
                align: "right",
                headerClassName: "w-[70px]",
                mobileLabel: "",
                cell: (m) => (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => setDeleteConfirm({ id: m.id, name: m.name })}
                    title="Delete Mapping"
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                ),
              },
            ]}
          />
        )}
      </CollapsibleSection>

      {/* Add Broadcaster Mapping Dialog */}
      <Dialog open={showDialog} onOpenChange={(open) => !open && setShowDialog(false)}>
        <DialogContent onClose={() => setShowDialog(false)}>
          <DialogHeader>
            <DialogTitle>Add Broadcaster / RSN Mapping</DialogTitle>
            <DialogDescription>
              Map a stream name, regex pattern, or tvg-id to a specific team's broadcast feed.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold">Mapping Label</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g., MASN Orioles, NESN 4K"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold">Match Type</label>
                <Select
                  value={form.pattern_type}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      pattern_type: e.target.value as "regex" | "exact" | "tvg_id" | "channel_id",
                    }))
                  }
                >
                  <option value="regex">Regex Pattern</option>
                  <option value="exact">Exact Name Match</option>
                  <option value="tvg_id">tvg-id Match</option>
                  <option value="channel_id">Dispatcharr Channel ID</option>
                </Select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold">Match Pattern / Value</label>
                <Input
                  value={form.pattern}
                  onChange={(e) => setForm((f) => ({ ...f, pattern: e.target.value }))}
                  placeholder={
                    form.pattern_type === "regex"
                      ? "(?i)\\bMASN\\b"
                      : form.pattern_type === "tvg_id"
                      ? "MASN.us"
                      : "MASN"
                  }
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold">League</label>
              <LeaguePicker
                selectedLeagues={form.league ? [form.league] : []}
                onSelectionChange={(leagues) => {
                  const league = leagues[0] || "mlb"
                  setForm((f) => ({ ...f, league, team_id: "", team_name: "" }))
                  setSelectedTeams([])
                }}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold">Target Team</label>
              <TeamPicker
                leagues={[form.league]}
                selectedTeams={selectedTeams}
                onSelectionChange={handleTeamSelect}
                singleSelect={true}
                placeholder="Select the team this broadcaster airs"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={createMutation.isPending}>
              {createMutation.isPending ? "Adding..." : "Add Mapping"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        title="Delete Broadcaster Mapping"
        description={`Are you sure you want to delete the mapping "${deleteConfirm?.name}"?`}
        confirmLabel="Delete"
        confirmVariant="destructive"
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
      />
    </>
  )
}
