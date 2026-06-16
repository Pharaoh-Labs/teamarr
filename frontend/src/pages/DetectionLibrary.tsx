import { useState, useRef } from "react"
import { toast } from "sonner"
import {
  Plus,
  Trash2,
  Pencil,
  Loader2,
  Download,
  Upload,
  ToggleLeft,
  ToggleRight,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { EpgMatchingSettings, EventLookaheadSetting } from "@/components/EventMatchingSettings"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ResponsiveTable, type ResponsiveColumn } from "@/components/ui/responsive-table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  useDetectionKeywords,
  useDetectionCategories,
  useCreateDetectionKeyword,
  useUpdateDetectionKeyword,
  useDeleteDetectionKeyword,
  useBulkImportDetectionKeywords,
  exportDetectionKeywords,
  type CategoryType,
  type DetectionKeyword,
  type DetectionKeywordCreate,
} from "@/api/detectionKeywords"
import {
  useAliases,
  useCreateAlias,
  useDeleteAlias,
  exportAliases,
  useImportAliases,
} from "@/api/aliases"
import { TeamPicker } from "@/components/TeamPicker"
import { LeaguePicker } from "@/components/LeaguePicker"
import { SubNav } from "@/components/ui/sub-nav"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import type { TeamFilterEntry } from "@/api/types"

// Tab types - detection keyword categories plus team_aliases
type TabType = CategoryType | "team_aliases"

// Detection Library sections: classification concerns plus matchup separators.
// Surfaced sections (in render order): team_aliases, event_type_keywords,
// league_hints, sport_hints, separators.
// Separators are global (detection_keywords category 'separators') and let users
// teach the classifier locale-specific matchup delimiters — e.g. " - " for
// "España - Inglaterra" — without us shipping risky defaults (a bare hyphen
// over-splits English titles). The remaining extraction categories
// (placeholders, card_segments, exclusions) aren't exposed as sections yet; they
// are managed via import/export or the API.

// Full mapping for type safety. Categories not surfaced as sections are not
// shown in the UI yet (import/export or API only).
const TAB_NAMES: Record<TabType, string> = {
  team_aliases: "Team Aliases",
  event_type_keywords: "Event Type Detection",
  league_hints: "League Hints",
  sport_hints: "Sport Hints",
  separators: "Separators",
  // Not yet exposed as tabs (managed via import/export or API)
  placeholders: "Placeholders",
  card_segments: "Card Segments",
  exclusions: "Combat Exclusions",
}

/** Parse a sport hint target_value, which may be a JSON array or plain string. */
function parseSportTarget(value: string | null): string[] {
  if (!value) return []
  if (value.startsWith("[")) {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.filter((s: unknown) => typeof s === "string")
    } catch {
      // fall through
    }
  }
  return [value]
}

/** Serialize sport targets for storage. Single value → plain string, multiple → JSON array. */
function serializeSportTarget(sports: string[]): string {
  if (sports.length === 0) return ""
  if (sports.length === 1) return sports[0]
  return JSON.stringify(sports)
}

/**
 * Prepare a keyword for storage. Separators carry semantically meaningful
 * leading/trailing spaces (" - ", " vs ") that keep substring matching from
 * splitting mid-word, so they are preserved verbatim. Every other category is
 * trimmed to drop accidental whitespace.
 */
function prepareKeyword(category: TabType, raw: string): string {
  return category === "separators" ? raw : raw.trim()
}

export function DetectionLibrary() {
  const [activeView, setActiveView] = useState<
    "custom_rules" | "epg_matching" | "event_lookahead"
  >("epg_matching")
  const [activeTab, setActiveTab] = useState<TabType>("team_aliases")
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [editingKeyword, setEditingKeyword] = useState<DetectionKeyword | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<DetectionKeyword | null>(null)
  const [deleteAliasConfirm, setDeleteAliasConfirm] = useState<{ id: number; alias: string } | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Detection keywords queries. Per-category keyword fetching now lives in each
  // KeywordSection (a section can't share one query — hooks can't loop).
  const categoriesQuery = useDetectionCategories()
  const createMutation = useCreateDetectionKeyword()
  const updateMutation = useUpdateDetectionKeyword()
  const deleteMutation = useDeleteDetectionKeyword()
  const importMutation = useBulkImportDetectionKeywords()

  // Aliases queries
  const aliasesQuery = useAliases()
  const createAliasMutation = useCreateAlias()
  const deleteAliasMutation = useDeleteAlias()
  const importAliasesMutation = useImportAliases()

  const categories = categoriesQuery.data?.categories || []
  const aliases = aliasesQuery.data?.aliases || []
  // activeInfo drives the Add/Edit dialog copy for the currently-acted category.
  const activeInfo = categories.find((c) => c.id === activeTab)

  // Keyword form state
  const [formData, setFormData] = useState<{
    keyword: string
    is_regex: boolean
    target_value: string
    enabled: boolean
    priority: number
    description: string
  }>({
    keyword: "",
    is_regex: false,
    target_value: "",
    enabled: true,
    priority: 0,
    description: "",
  })

  // Alias form state
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
  const [showAliasDialog, setShowAliasDialog] = useState(false)

  const resetForm = () => {
    setFormData({
      keyword: "",
      is_regex: false,
      target_value: "",
      enabled: true,
      priority: 0,
      description: "",
    })
  }

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

  // `category` overrides the stale `activeTab` closure value when called from a
  // section (setActiveTab hasn't flushed in the same tick). Defaults to activeTab.
  const openAddDialog = (category: TabType = activeTab) => {
    if (category === "team_aliases") {
      resetAliasForm()
      setShowAliasDialog(true)
    } else {
      resetForm()
      setShowAddDialog(true)
    }
  }

  const openEditDialog = (keyword: DetectionKeyword, category: TabType = activeTab) => {
    let displayTarget = keyword.target_value || ""
    // Deserialize JSON arrays to comma-separated for sport_hints editing
    if (category === "sport_hints" && displayTarget.startsWith("[")) {
      const sports = parseSportTarget(displayTarget)
      displayTarget = sports.join(", ")
    }
    setFormData({
      keyword: keyword.keyword,
      is_regex: keyword.is_regex,
      target_value: displayTarget,
      enabled: keyword.enabled,
      priority: keyword.priority,
      description: keyword.description || "",
    })
    setEditingKeyword(keyword)
  }

  const handleCreate = async () => {
    try {
      let targetValue = formData.target_value.trim() || null
      if (targetValue && activeTab === "sport_hints" && targetValue.includes(",")) {
        const sports = targetValue.split(",").map((s) => s.trim()).filter(Boolean)
        targetValue = serializeSportTarget(sports)
      }
      const data: DetectionKeywordCreate = {
        category: activeTab as CategoryType,
        keyword: prepareKeyword(activeTab, formData.keyword),
        is_regex: formData.is_regex,
        target_value: targetValue,
        enabled: formData.enabled,
        priority: formData.priority,
        description: formData.description.trim() || null,
      }
      await createMutation.mutateAsync(data)
      toast.success(`Created keyword "${data.keyword}"`)
      setShowAddDialog(false)
      resetForm()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create keyword")
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

  const handleUpdate = async () => {
    if (!editingKeyword) return
    try {
      let targetValue = formData.target_value.trim() || null
      if (targetValue && activeTab === "sport_hints" && targetValue.includes(",")) {
        const sports = targetValue.split(",").map((s) => s.trim()).filter(Boolean)
        targetValue = serializeSportTarget(sports)
      }
      await updateMutation.mutateAsync({
        id: editingKeyword.id,
        data: {
          keyword: prepareKeyword(activeTab, formData.keyword),
          is_regex: formData.is_regex,
          target_value: targetValue,
          enabled: formData.enabled,
          priority: formData.priority,
          description: formData.description.trim() || null,
          clear_target_value: !formData.target_value.trim(),
          clear_description: !formData.description.trim(),
        },
      })
      toast.success(`Updated keyword "${formData.keyword}"`)
      setEditingKeyword(null)
      resetForm()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update keyword")
    }
  }

  const handleDelete = async () => {
    if (!deleteConfirm) return
    try {
      await deleteMutation.mutateAsync(deleteConfirm.id)
      toast.success(`Deleted keyword "${deleteConfirm.keyword}"`)
      setDeleteConfirm(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete keyword")
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

  const handleToggleEnabled = async (keyword: DetectionKeyword) => {
    try {
      await updateMutation.mutateAsync({
        id: keyword.id,
        data: { enabled: !keyword.enabled },
      })
      toast.success(`${keyword.enabled ? "Disabled" : "Enabled"} keyword "${keyword.keyword}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to toggle keyword")
    }
  }

  // `category` overrides the stale `activeTab` closure value when called from a
  // section (setActiveTab hasn't flushed in the same tick). Defaults to activeTab.
  const handleExport = async (category: TabType = activeTab) => {
    try {
      if (category === "team_aliases") {
        const data = await exportAliases()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = "team-aliases.json"
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        toast.success(`Exported ${data.length} aliases`)
      } else {
        const data = await exportDetectionKeywords(category as CategoryType)
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `detection-keywords-${category}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        toast.success(`Exported ${data.count} keywords`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to export")
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsImporting(true)
    try {
      const text = await file.text()
      const imported = JSON.parse(text)

      if (activeTab === "team_aliases") {
        const aliases = Array.isArray(imported) ? imported : imported.aliases
        if (!Array.isArray(aliases)) {
          throw new Error("Invalid format: expected aliases array")
        }
        const result = await importAliasesMutation.mutateAsync(aliases)
        toast.success(`Imported: ${result.created} created, ${result.skipped} skipped`)
      } else {
        const keywords = Array.isArray(imported) ? imported : imported.keywords
        if (!Array.isArray(keywords)) {
          throw new Error("Invalid format: expected keywords array")
        }
        const result = await importMutation.mutateAsync({ keywords })
        toast.success(`Imported: ${result.created} created, ${result.updated} updated`)
        if (result.failed > 0) {
          toast.warning(`${result.failed} keywords failed to import`)
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to import")
    } finally {
      setIsImporting(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  // Shared action buttons (Add / Import / Export) for a section header. Each
  // sets activeTab to the section's category BEFORE invoking the existing
  // handler so dialogs/import/export target the right category.
  const SectionActions = ({ category }: { category: TabType }) => (
    <>
      <Button
        size="sm"
        onClick={() => {
          setActiveTab(category)
          openAddDialog(category)
        }}
      >
        <Plus className="h-4 w-4 mr-1" />
        {category === "team_aliases" ? "Add Alias" : "Add Keyword"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setActiveTab(category)
          handleImportClick()
        }}
        disabled={isImporting}
        title="Import"
      >
        {isImporting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Upload className="h-4 w-4" />
        )}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setActiveTab(category)
          handleExport(category)
        }}
        title="Export"
      >
        <Download className="h-4 w-4" />
      </Button>
    </>
  )

  // Team Aliases section — fetches its own data via the shared aliases query.
  const AliasSection = () => (
    <CollapsibleSection
      title={TAB_NAMES.team_aliases}
      count={aliases.length}
      actions={<SectionActions category="team_aliases" />}
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
                    onClick={() => {
                      setActiveTab("team_aliases")
                      setDeleteAliasConfirm({ id: alias.id, alias: alias.alias })
                    }}
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
  )

  // Keyword section — fetches its OWN category's keywords via the hook.
  const KeywordSection = ({ category }: { category: CategoryType }) => {
    const query = useDetectionKeywords(category)
    const sectionKeywords = query.data?.keywords || []
    const info = categories.find((c) => c.id === category)
    return (
      <CollapsibleSection
        title={TAB_NAMES[category]}
        count={sectionKeywords.length}
        actions={<SectionActions category={category} />}
        persistKey={`detlib-${category}`}
      >
        {info && (
          <p className="text-sm text-muted-foreground mb-2">
            {info.description}
            {info.has_target && info.target_description && (
              <span className="ml-2 text-primary">Target: {info.target_description}</span>
            )}
          </p>
        )}
        {query.isLoading ? (
          <div className="flex items-center justify-center rounded-lg border border-border py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ResponsiveTable
            className="rounded-lg border border-border overflow-hidden"
            rows={sectionKeywords}
            keyExtractor={(kw) => kw.id}
            rowClassName={(kw) => (!kw.enabled ? "opacity-50" : undefined)}
            emptyMessage="No keywords in this category. Add one to get started."
            columns={[
              {
                key: "keyword",
                header: "Keyword/Pattern",
                headerClassName: "w-[40%]",
                mobileTitle: true,
                cell: (kw: DetectionKeyword) => (
                  <div className="flex flex-col">
                    <code className="text-sm font-mono bg-muted px-1 rounded">{kw.keyword}</code>
                    {kw.description && (
                      <span className="text-xs text-muted-foreground mt-0.5">{kw.description}</span>
                    )}
                  </div>
                ),
              },
              info?.has_target
                ? {
                    key: "target",
                    header: "Target",
                    headerClassName: "w-[20%]",
                    cell: (kw: DetectionKeyword) =>
                      kw.target_value ? (
                        category === "sport_hints" && kw.target_value.startsWith("[") ? (
                          <div className="flex gap-1 flex-wrap">
                            {parseSportTarget(kw.target_value).map((s) => (
                              <Badge key={s} variant="secondary" className="text-xs font-mono">
                                {s}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <code className="text-sm font-mono">{kw.target_value}</code>
                        )
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      ),
                  }
                : null,
              {
                key: "type",
                header: "Type",
                headerClassName: "w-[80px]",
                cell: (kw: DetectionKeyword) => (
                  <Badge variant={kw.is_regex ? "info" : "secondary"}>
                    {kw.is_regex ? "regex" : "text"}
                  </Badge>
                ),
              },
              {
                key: "priority",
                header: "Priority",
                headerClassName: "w-[80px]",
                cell: (kw: DetectionKeyword) => <span className="text-sm">{kw.priority}</span>,
              },
              {
                key: "status",
                header: "Status",
                headerClassName: "w-[80px]",
                cell: (kw: DetectionKeyword) => (
                  <Badge variant={kw.enabled ? "success" : "secondary"}>
                    {kw.enabled ? "On" : "Off"}
                  </Badge>
                ),
              },
              {
                key: "actions",
                header: "Actions",
                align: "right",
                headerClassName: "w-[120px]",
                mobileLabel: "",
                cell: (kw: DetectionKeyword) => (
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setActiveTab(category)
                        handleToggleEnabled(kw)
                      }}
                      title={kw.enabled ? "Disable" : "Enable"}
                    >
                      {kw.enabled ? (
                        <ToggleRight className="h-4 w-4 text-green-500" />
                      ) : (
                        <ToggleLeft className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setActiveTab(category)
                        openEditDialog(kw, category)
                      }}
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => {
                        setActiveTab(category)
                        setDeleteConfirm(kw)
                      }}
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                ),
              },
            ].filter(Boolean) as ResponsiveColumn<(typeof sectionKeywords)[number]>[]}
          />
        )}
      </CollapsibleSection>
    )
  }

  if (categoriesQuery.error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Matching</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Error loading categories: {categoriesQuery.error.message}
            </p>
            <Button className="mt-4" onClick={() => categoriesQuery.refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-xl font-bold shrink-0">Matching</h1>
        {/* Custom Regex signpost — compact one-liner beside the heading */}
        <div className="rounded-md border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950 px-3 py-1.5 text-xs text-blue-800 dark:text-blue-200 sm:whitespace-nowrap">
          <span className="font-semibold text-blue-900 dark:text-blue-100">Tip:</span>{" "}
          per-source <strong>Custom Regex</strong> is your strongest matching lever — set it in Sources.
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={handleImportFile}
        />
      </div>

      {/* Page-level view nav */}
      <SubNav
        items={[
          { key: "epg_matching", label: "EPG Matching" },
          { key: "event_lookahead", label: "Event Lookahead" },
          { key: "custom_rules", label: "Custom Rules" },
        ]}
        value={activeView}
        onChange={(k) =>
          setActiveView(k as "custom_rules" | "epg_matching" | "event_lookahead")
        }
      />

      {activeView === "epg_matching" && <EpgMatchingSettings />}

      {activeView === "event_lookahead" && <EventLookaheadSetting />}

      {activeView === "custom_rules" && (
        <div className="space-y-4">
          <AliasSection />
          <KeywordSection category="event_type_keywords" />
          <KeywordSection category="league_hints" />
          <KeywordSection category="sport_hints" />
          <KeywordSection category="separators" />
        </div>
      )}

      {/* Add Keyword Dialog */}
      <Dialog
        open={showAddDialog || editingKeyword !== null}
        onOpenChange={(open) => {
          if (!open) {
            setShowAddDialog(false)
            setEditingKeyword(null)
            resetForm()
          }
        }}
      >
        <DialogContent
          onClose={() => {
            setShowAddDialog(false)
            setEditingKeyword(null)
            resetForm()
          }}
        >
          <DialogHeader>
            <DialogTitle>{editingKeyword ? "Edit Keyword" : "Add Keyword"}</DialogTitle>
            <DialogDescription>
              {activeInfo?.description}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Keyword/Pattern</label>
              <Input
                value={formData.keyword}
                onChange={(e) => setFormData((f) => ({ ...f, keyword: e.target.value }))}
                placeholder={formData.is_regex ? "regex pattern" : "keyword text"}
              />
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.is_regex}
                  onCheckedChange={(checked) => setFormData((f) => ({ ...f, is_regex: checked }))}
                />
                <label className="text-sm">Regular expression</label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.enabled}
                  onCheckedChange={(checked) => setFormData((f) => ({ ...f, enabled: checked }))}
                />
                <label className="text-sm">Enabled</label>
              </div>
            </div>

            {activeInfo?.has_target && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  Target Value
                  {activeInfo.target_description && (
                    <span className="text-muted-foreground font-normal ml-1">
                      ({activeInfo.target_description})
                    </span>
                  )}
                </label>
                <Input
                  value={formData.target_value}
                  onChange={(e) => setFormData((f) => ({ ...f, target_value: e.target.value }))}
                  placeholder={activeTab === "sport_hints"
                    ? "e.g., Hockey or Soccer, Football for multiple"
                    : "e.g., nfl, Hockey, main_card"}
                />
                {activeTab === "sport_hints" && (
                  <p className="text-xs text-muted-foreground">
                    Comma-separated for multiple sports (e.g., &quot;Soccer, Football&quot; for ambiguous terms)
                  </p>
                )}
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">Priority</label>
              <Input
                type="number"
                value={formData.priority}
                onChange={(e) =>
                  setFormData((f) => ({ ...f, priority: parseInt(e.target.value) || 0 }))
                }
                placeholder="0"
              />
              <p className="text-xs text-muted-foreground">
                Higher priority patterns are checked first
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                value={formData.description}
                onChange={(e) => setFormData((f) => ({ ...f, description: e.target.value }))}
                placeholder="Optional description"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowAddDialog(false)
                setEditingKeyword(null)
                resetForm()
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={editingKeyword ? handleUpdate : handleCreate}
              disabled={
                !formData.keyword.trim() ||
                createMutation.isPending ||
                updateMutation.isPending
              }
            >
              {(createMutation.isPending || updateMutation.isPending) && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              {editingKeyword ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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

      {/* Delete Keyword Confirmation */}
      <Dialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
      >
        <DialogContent onClose={() => setDeleteConfirm(null)}>
          <DialogHeader>
            <DialogTitle>Delete Keyword</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deleteConfirm?.keyword}"? This cannot be undone.
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
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Alias Confirmation */}
      <Dialog
        open={deleteAliasConfirm !== null}
        onOpenChange={(open) => !open && setDeleteAliasConfirm(null)}
      >
        <DialogContent onClose={() => setDeleteAliasConfirm(null)}>
          <DialogHeader>
            <DialogTitle>Delete Alias</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete alias "{deleteAliasConfirm?.alias}"? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteAliasConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteAlias}
              disabled={deleteAliasMutation.isPending}
            >
              {deleteAliasMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
