import { useRef, useState } from "react"
import { toast } from "sonner"
import { Trash2, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { ResponsiveTable } from "@/components/ui/responsive-table"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  useAliases,
  useCreateAlias,
  useDeleteAlias,
  exportAliases,
  useImportAliases,
} from "@/api/aliases"
import { TeamPicker } from "@/components/TeamPicker"
import { LeaguePicker } from "@/components/LeaguePicker"
import type { TeamFilterEntry } from "@/api/types"
import { TAB_NAMES, downloadJson } from "./helpers"
import { SectionActions } from "./SectionActions"

/**
 * Team Aliases section — maps alternate team names to official names.
 * Fully self-contained: owns its query, add dialog, delete confirm, and
 * import/export.
 */
export function AliasesSection() {
  const aliasesQuery = useAliases()
  const createAliasMutation = useCreateAlias()
  const deleteAliasMutation = useDeleteAlias()
  const importAliasesMutation = useImportAliases()

  const aliases = aliasesQuery.data?.aliases || []

  const [showAliasDialog, setShowAliasDialog] = useState(false)
  const [deleteAliasConfirm, setDeleteAliasConfirm] = useState<{ id: number; alias: string } | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [aliasForm, setAliasForm] = useState<{
    alias: string
    league: string
    team_id: string
    team_name: string
  }>({
    alias: "",
    league: "",
    team_id: "",
    team_name: "",
  })
  const [aliasSelectedTeams, setAliasSelectedTeams] = useState<TeamFilterEntry[]>([])

  const resetAliasForm = () => {
    setAliasForm({ alias: "", league: "", team_id: "", team_name: "" })
    setAliasSelectedTeams([])
  }

  // Handle team selection from TeamPicker
  const handleAliasTeamSelect = (teams: TeamFilterEntry[]) => {
    setAliasSelectedTeams(teams)
    const team = teams[0]
    if (team) {
      setAliasForm((f) => ({
        ...f,
        team_id: team.team_id,
        team_name: team.name || "",
      }))
    } else {
      setAliasForm((f) => ({ ...f, team_id: "", team_name: "" }))
    }
  }

  const handleCreateAlias = async () => {
    try {
      await createAliasMutation.mutateAsync({
        alias: aliasForm.alias.trim(),
        league: aliasForm.league,
        team_id: aliasForm.team_id,
        team_name: aliasForm.team_name,
      })
      toast.success(`Created alias "${aliasForm.alias}"`)
      setShowAliasDialog(false)
      resetAliasForm()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create alias")
    }
  }

  const handleDeleteAlias = async () => {
    if (!deleteAliasConfirm) return
    try {
      await deleteAliasMutation.mutateAsync(deleteAliasConfirm.id)
      toast.success(`Deleted alias "${deleteAliasConfirm.alias}"`)
      setDeleteAliasConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete alias")
    }
  }

  const handleExport = async () => {
    try {
      const data = await exportAliases()
      downloadJson(data, "team-aliases.json")
      toast.success(`Exported ${data.length} aliases`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to export")
    }
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsImporting(true)
    try {
      const text = await file.text()
      const imported = JSON.parse(text)
      const importedAliases = Array.isArray(imported) ? imported : imported.aliases
      if (!Array.isArray(importedAliases)) {
        throw new Error("Invalid format: expected aliases array")
      }
      const result = await importAliasesMutation.mutateAsync(importedAliases)
      toast.success(`Imported: ${result.created} created, ${result.skipped} skipped`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to import")
    } finally {
      setIsImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleImportFile}
      />

      <CollapsibleSection
        title={TAB_NAMES.team_aliases}
        count={aliases.length}
        actions={
          <SectionActions
            addLabel="Add Alias"
            onAdd={() => {
              resetAliasForm()
              setShowAliasDialog(true)
            }}
            onImport={() => fileInputRef.current?.click()}
            onExport={handleExport}
            isImporting={isImporting}
          />
        }
        persistKey="detlib-team_aliases"
      >
        <p className="text-sm text-muted-foreground mb-2">
          Map alternate team names to their official names for better stream matching
        </p>
        {aliasesQuery.isLoading ? (
          <div className="flex items-center justify-center rounded-lg border border-border py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ResponsiveTable
            className="rounded-lg border border-border overflow-hidden"
            rows={aliases}
            keyExtractor={(alias) => alias.id}
            emptyMessage="No team aliases configured. Add one to get started."
            columns={[
              {
                key: "alias",
                header: "Alias",
                headerClassName: "w-[30%]",
                mobileTitle: true,
                cell: (alias) => (
                  <code className="text-sm font-mono bg-muted px-1 rounded">{alias.alias}</code>
                ),
              },
              {
                key: "team_name",
                header: "Maps To",
                headerClassName: "w-[30%]",
                cell: (alias) => alias.team_name,
              },
              {
                key: "league",
                header: "League",
                headerClassName: "w-[20%]",
                cell: (alias) => <Badge variant="secondary">{alias.league}</Badge>,
              },
              {
                key: "actions",
                header: "Actions",
                align: "right",
                headerClassName: "w-[80px]",
                mobileLabel: "",
                cell: (alias) => (
                  <div className="flex items-center justify-end">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => setDeleteAliasConfirm({ id: alias.id, alias: alias.alias })}
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                ),
              },
            ]}
          />
        )}
      </CollapsibleSection>

      {/* Add Alias Dialog */}
      <Dialog open={showAliasDialog} onOpenChange={(open) => !open && setShowAliasDialog(false)}>
        <DialogContent onClose={() => setShowAliasDialog(false)}>
          <DialogHeader>
            <DialogTitle>Add Team Alias</DialogTitle>
            <DialogDescription>
              Map an alternate team name to its official name
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Alias Text</label>
              <Input
                value={aliasForm.alias}
                onChange={(e) => setAliasForm((f) => ({ ...f, alias: e.target.value }))}
                placeholder="e.g., Niners, Bolts, Leafs"
              />
              <p className="text-xs text-muted-foreground">
                The alternate name that appears in stream names
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">League</label>
              <LeaguePicker
                selectedLeagues={aliasForm.league ? [aliasForm.league] : []}
                onSelectionChange={(leagues) => {
                  const league = leagues[0] || ""
                  setAliasForm((f) => ({ ...f, league, team_id: "", team_name: "" }))
                  setAliasSelectedTeams([])
                }}
                singleSelect
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Maps To Team</label>
              {!aliasForm.league ? (
                <p className="text-sm text-muted-foreground py-2">Select a league first</p>
              ) : (
                <TeamPicker
                  leagues={[aliasForm.league]}
                  selectedTeams={aliasSelectedTeams}
                  onSelectionChange={handleAliasTeamSelect}
                  singleSelect
                  placeholder="Search for team..."
                />
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAliasDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateAlias}
              disabled={
                !aliasForm.alias.trim() ||
                !aliasForm.team_id ||
                createAliasMutation.isPending
              }
            >
              {createAliasMutation.isPending && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Alias Confirmation */}
      <ConfirmDialog
        open={deleteAliasConfirm !== null}
        onOpenChange={(open) => !open && setDeleteAliasConfirm(null)}
        title="Delete Alias"
        description={`Are you sure you want to delete alias "${deleteAliasConfirm?.alias}"? This cannot be undone.`}
        confirmLabel="Delete"
        isPending={deleteAliasMutation.isPending}
        onConfirm={handleDeleteAlias}
      />
    </>
  )
}
