import { useRef, useState } from "react"
import { toast } from "sonner"
import { Trash2, Pencil, Loader2, ToggleLeft, ToggleRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
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
  type CategoryInfo,
} from "@/api/detectionKeywords"
import {
  TAB_NAMES,
  parseSportTarget,
  serializeSportTarget,
  prepareKeyword,
  downloadJson,
} from "./helpers"
import { SectionActions } from "./SectionActions"

// Keyword categories surfaced as sections, in render order.
const SECTION_CATEGORIES: CategoryType[] = [
  "event_type_keywords",
  "league_hints",
  "sport_hints",
  "separators",
]

interface KeywordFormData {
  keyword: string
  is_regex: boolean
  target_value: string
  enabled: boolean
  priority: number
  description: string
}

const EMPTY_FORM: KeywordFormData = {
  keyword: "",
  is_regex: false,
  target_value: "",
  enabled: true,
  priority: 0,
  description: "",
}

/**
 * Detection keyword sections (event types, league/sport hints, separators)
 * plus the shared Add/Edit dialog, delete confirm, and per-category
 * import/export. Fully self-contained.
 */
export function KeywordSections() {
  const categoriesQuery = useDetectionCategories()
  const createMutation = useCreateDetectionKeyword()
  const updateMutation = useUpdateDetectionKeyword()
  const deleteMutation = useDeleteDetectionKeyword()
  const importMutation = useBulkImportDetectionKeywords()

  const categories = categoriesQuery.data?.categories || []

  // The category the Add/Edit/Import dialog currently targets. Set explicitly
  // by each section's action handlers before opening a dialog or file picker.
  const [activeCategory, setActiveCategory] = useState<CategoryType>("event_type_keywords")
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [editingKeyword, setEditingKeyword] = useState<DetectionKeyword | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<DetectionKeyword | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [formData, setFormData] = useState<KeywordFormData>(EMPTY_FORM)
  const resetForm = () => setFormData(EMPTY_FORM)

  // Dialog copy for the currently-acted category.
  const activeInfo = categories.find((c) => c.id === activeCategory)

  const openAddDialog = (category: CategoryType) => {
    setActiveCategory(category)
    resetForm()
    setShowAddDialog(true)
  }

  const openEditDialog = (keyword: DetectionKeyword, category: CategoryType) => {
    setActiveCategory(category)
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

  const serializeTarget = (raw: string): string | null => {
    let targetValue = raw.trim() || null
    if (targetValue && activeCategory === "sport_hints" && targetValue.includes(",")) {
      const sports = targetValue.split(",").map((s) => s.trim()).filter(Boolean)
      targetValue = serializeSportTarget(sports)
    }
    return targetValue
  }

  const handleCreate = async () => {
    try {
      const data: DetectionKeywordCreate = {
        category: activeCategory,
        keyword: prepareKeyword(activeCategory, formData.keyword),
        is_regex: formData.is_regex,
        target_value: serializeTarget(formData.target_value),
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

  const handleUpdate = async () => {
    if (!editingKeyword) return
    try {
      await updateMutation.mutateAsync({
        id: editingKeyword.id,
        data: {
          keyword: prepareKeyword(activeCategory, formData.keyword),
          is_regex: formData.is_regex,
          target_value: serializeTarget(formData.target_value),
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

  const handleExport = async (category: CategoryType) => {
    try {
      const data = await exportDetectionKeywords(category)
      downloadJson(data, `detection-keywords-${category}.json`)
      toast.success(`Exported ${data.count} keywords`)
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
      const keywords = Array.isArray(imported) ? imported : imported.keywords
      if (!Array.isArray(keywords)) {
        throw new Error("Invalid format: expected keywords array")
      }
      const result = await importMutation.mutateAsync({ keywords })
      toast.success(`Imported: ${result.created} created, ${result.updated} updated`)
      if (result.failed > 0) {
        toast.warning(`${result.failed} keywords failed to import`)
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

  if (categoriesQuery.error) {
    return (
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
    )
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

      {SECTION_CATEGORIES.map((category) => (
        <KeywordSection
          key={category}
          category={category}
          info={categories.find((c) => c.id === category)}
          isImporting={isImporting}
          onAdd={() => openAddDialog(category)}
          onImport={() => {
            setActiveCategory(category)
            fileInputRef.current?.click()
          }}
          onExport={() => handleExport(category)}
          onEdit={(kw) => openEditDialog(kw, category)}
          onDelete={(kw) => setDeleteConfirm(kw)}
          onToggle={handleToggleEnabled}
        />
      ))}

      {/* Add/Edit Keyword Dialog */}
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
                  placeholder={activeCategory === "sport_hints"
                    ? "e.g., Hockey or Soccer, Football for multiple"
                    : "e.g., nfl, Hockey, main_card"}
                />
                {activeCategory === "sport_hints" && (
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

      {/* Delete Keyword Confirmation */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        title="Delete Keyword"
        description={`Are you sure you want to delete "${deleteConfirm?.keyword}"? This cannot be undone.`}
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
      />
    </>
  )
}

interface KeywordSectionProps {
  category: CategoryType
  info: CategoryInfo | undefined
  isImporting: boolean
  onAdd: () => void
  onImport: () => void
  onExport: () => void
  onEdit: (kw: DetectionKeyword) => void
  onDelete: (kw: DetectionKeyword) => void
  onToggle: (kw: DetectionKeyword) => void
}

// One collapsible keyword-category section. Fetches its OWN category's
// keywords via the hook (sections can't share one query — hooks can't loop).
function KeywordSection({
  category,
  info,
  isImporting,
  onAdd,
  onImport,
  onExport,
  onEdit,
  onDelete,
  onToggle,
}: KeywordSectionProps) {
  const query = useDetectionKeywords(category)
  const sectionKeywords = query.data?.keywords || []
  return (
    <CollapsibleSection
      title={TAB_NAMES[category]}
      count={sectionKeywords.length}
      actions={
        <SectionActions
          addLabel="Add Keyword"
          onAdd={onAdd}
          onImport={onImport}
          onExport={onExport}
          isImporting={isImporting}
        />
      }
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
                    onClick={() => onToggle(kw)}
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
                    onClick={() => onEdit(kw)}
                    title="Edit"
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => onDelete(kw)}
                    title="Delete"
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ),
            },
          ].filter(Boolean) as ResponsiveColumn<DetectionKeyword>[]}
        />
      )}
    </CollapsibleSection>
  )
}
