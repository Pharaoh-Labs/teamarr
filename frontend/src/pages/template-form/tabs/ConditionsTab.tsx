import { useState, useMemo } from "react"
import { toast } from "sonner"
import { BookOpen, Download, Upload, Trash2, Loader2, ChevronRight, Target } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import type { ConditionalDescription } from "@/api/templates"
import { fetchConditions } from "@/api/variables"
import { usePresets, useCreatePreset, useDeletePreset } from "@/hooks/usePresets"
import type { ConditionPreset } from "@/api/presets"
import type { TabProps } from "../types"

export function ConditionsTab({ formData, setFormData, resolveTemplate, isTeamTemplate }: TabProps) {
  // Filter out fallback descriptions (priority=100) - they're managed on Defaults tab
  const conditions = useMemo(() => {
    return (formData.conditional_descriptions || []).filter((c) => c.priority !== 100)
  }, [formData.conditional_descriptions])
  const [showPresetDialog, setShowPresetDialog] = useState(false)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [presetName, setPresetName] = useState("")
  const [presetDescription, setPresetDescription] = useState("")
  const [expandedConditions, setExpandedConditions] = useState<Set<number>>(new Set())

  // Fetch available conditions from API (filtered by template type)
  const templateType = isTeamTemplate ? "team" : "event"
  const { data: conditionsData } = useQuery({
    queryKey: ["conditions", templateType],
    queryFn: () => fetchConditions(templateType),
    staleTime: 5 * 60 * 1000, // 5 minutes - allow refetch when conditions change
  })
  const availableConditions = conditionsData?.conditions || []

  // Presets hooks
  const { data: presets, isLoading: presetsLoading } = usePresets()
  const createPresetMutation = useCreatePreset()
  const deletePresetMutation = useDeletePreset()

  const addCondition = () => {
    // Default to first available condition, or is_home as fallback
    const defaultCondition = availableConditions.length > 0 ? availableConditions[0].name : "is_home"
    const newCondition: ConditionalDescription = {
      condition: defaultCondition,
      template: "",
      priority: 50, // Default conditional priority (not 100 which is for fallbacks)
    }
    setFormData((prev) => {
      const all = prev.conditional_descriptions || []
      const prevConditions = all.filter((c) => c.priority !== 100)
      const fallbacks = all.filter((c) => c.priority === 100)
      return { ...prev, conditional_descriptions: [...prevConditions, newCondition, ...fallbacks] }
    })
    // Auto-expand the new condition
    setExpandedConditions((prev) => new Set([...prev, conditions.length]))
  }

  const updateCondition = (index: number, field: keyof ConditionalDescription, value: string | number) => {
    const updated = [...conditions]
    updated[index] = { ...updated[index], [field]: value }
    setFormData((prev) => {
      const fallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority === 100)
      return { ...prev, conditional_descriptions: [...updated, ...fallbacks] }
    })
  }

  const removeCondition = (index: number) => {
    const updated = conditions.filter((_, i) => i !== index)
    setFormData((prev) => {
      const fallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority === 100)
      return { ...prev, conditional_descriptions: [...updated, ...fallbacks] }
    })
    setExpandedConditions((prev) => {
      const newSet = new Set(prev)
      newSet.delete(index)
      // Shift higher indices down
      const shifted = new Set<number>()
      newSet.forEach((i) => shifted.add(i > index ? i - 1 : i))
      return shifted
    })
  }

  const toggleConditionExpanded = (index: number) => {
    setExpandedConditions((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(index)) {
        newSet.delete(index)
      } else {
        newSet.add(index)
      }
      return newSet
    })
  }

  const applyPreset = (preset: ConditionPreset) => {
    const presetConditions = preset.conditions.map((c) => ({
      condition: c.condition,
      template: c.template,
      priority: c.priority,
      condition_value: c.condition_value,
    }))
    setFormData((prev) => {
      const fallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority === 100)
      return { ...prev, conditional_descriptions: [...presetConditions, ...fallbacks] }
    })
    setShowPresetDialog(false)
    toast.success(`Applied preset "${preset.name}"`)
  }

  const handleSavePreset = async () => {
    if (!presetName.trim()) {
      toast.error("Preset name is required")
      return
    }
    if (conditions.length === 0) {
      toast.error("Add at least one condition before saving")
      return
    }

    try {
      await createPresetMutation.mutateAsync({
        name: presetName.trim(),
        description: presetDescription.trim() || undefined,
        conditions: conditions.map((c) => ({
          condition: c.condition,
          template: c.template,
          priority: c.priority,
          condition_value: c.condition_value,
        })),
      })
      toast.success(`Saved preset "${presetName}"`)
      setShowSaveDialog(false)
      setPresetName("")
      setPresetDescription("")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save preset")
    }
  }

  const handleDeletePreset = async (preset: ConditionPreset) => {
    if (!confirm(`Delete preset "${preset.name}"?`)) return
    try {
      await deletePresetMutation.mutateAsync(preset.id)
      toast.success(`Deleted preset "${preset.name}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete preset")
    }
  }

  // Get condition info for display
  const getConditionInfo = (condName: string) => {
    return availableConditions.find((c) => c.name === condName)
  }

  // Sort conditions by priority for display
  const sortedConditions = [...conditions].map((c, i) => ({ ...c, originalIndex: i })).sort((a, b) => a.priority - b.priority)

  return (
    <div className="space-y-4">
      {/* Preset Library Card */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              Preset Library
            </CardTitle>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowPresetDialog(true)}>
                <Download className="h-3 w-3 mr-1" />
                Load Preset
              </Button>
              <Button variant="outline" size="sm" onClick={() => setShowSaveDialog(true)} disabled={conditions.length === 0}>
                <Upload className="h-3 w-3 mr-1" />
                Save as Preset
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Save and reuse condition configurations across templates. Load a preset to apply its conditions, or save your current setup.
          </p>
        </CardContent>
      </Card>

      {/* Conditions Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2"><Target className="h-4 w-4" /> Conditional Descriptions</CardTitle>
            <Button onClick={addCondition} variant="outline" size="sm">
              + Add Condition
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Create dynamic descriptions based on specific conditions. Lower priority numbers are checked first.
            Priority 100 is reserved for fallback descriptions.
          </p>

          {conditions.length === 0 ? (
            <div className="text-center py-8 border-2 border-dashed rounded-lg">
              <p className="text-sm text-muted-foreground">
                No conditions defined. Add conditions to customize descriptions based on game context.
              </p>
              <Button onClick={addCondition} variant="outline" size="sm" className="mt-2">
                + Add First Condition
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {sortedConditions.map((cond) => {
                const idx = cond.originalIndex
                const isExpanded = expandedConditions.has(idx)
                const condInfo = getConditionInfo(cond.condition)
                const isFallback = cond.priority >= 100 || cond.condition === "always"

                return (
                  <div
                    key={idx}
                    className={`border rounded-lg overflow-hidden transition-all ${
                      isFallback ? "bg-amber-500/5 border-amber-500/30" : "bg-secondary/30"
                    }`}
                  >
                    {/* Collapsed header */}
                    <div
                      className="flex items-center gap-2 p-2 cursor-pointer hover:bg-secondary/50"
                      onClick={() => toggleConditionExpanded(idx)}
                    >
                      <ChevronRight className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        isFallback ? "bg-amber-500/20 text-amber-400" : "bg-primary/20 text-primary"
                      }`}>
                        P{cond.priority}
                      </span>
                      <span className="text-sm font-medium flex-1">
                        {condInfo?.description || cond.condition}
                        {cond.condition_value && ` (${cond.condition_value})`}
                        {condInfo?.providers === "espn" && (
                          <span className="ml-1 text-[10px] text-amber-500">(ESPN)</span>
                        )}
                      </span>
                      {cond.template && (
                        <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                          {cond.template.substring(0, 40)}{cond.template.length > 40 ? "..." : ""}
                        </span>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); removeCondition(idx) }}
                        className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>

                    {/* Expanded content */}
                    {isExpanded && (
                      <div className="p-3 pt-0 space-y-3 border-t">
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3">
                          <div>
                            <Label className="text-xs">Condition</Label>
                            <Select
                              value={cond.condition}
                              onChange={(e) => updateCondition(idx, "condition", e.target.value)}
                              className="h-8 text-sm"
                            >
                              {availableConditions.length > 0 ? (
                                availableConditions.map((c) => (
                                  <option key={c.name} value={c.name}>
                                    {c.description}{c.providers === "espn" ? " (ESPN only)" : ""}
                                  </option>
                                ))
                              ) : (
                                <>
                                  <option value="is_home">Team is playing at home</option>
                                  <option value="is_away">Team is playing away</option>
                                  <option value="win_streak">Team is on a win streak of N or more games</option>
                                  <option value="loss_streak">Team is on a loss streak of N or more games</option>
                                  <option value="is_ranked">Team is ranked (college sports)</option>
                                  <option value="is_ranked_opponent">Opponent is ranked (college sports)</option>
                                  <option value="is_ranked_matchup">Both teams are ranked (college sports)</option>
                                  <option value="is_top_ten_matchup">Both teams are ranked in top 10</option>
                                  <option value="is_conference_game">Game is a conference matchup</option>
                                  <option value="is_playoff">Game is a playoff/postseason game</option>
                                  <option value="is_preseason">Game is a preseason game</option>
                                  <option value="is_national_broadcast">Game is on national TV</option>
                                  <option value="has_odds">Betting odds are available for the game</option>
                                  <option value="opponent_name_contains">Opponent name contains specific text</option>
                                </>
                              )}
                            </Select>
                          </div>
                          {condInfo?.requires_value && (
                            <div>
                              <Label className="text-xs">Value</Label>
                              <Input
                                type={condInfo.value_type === "number" ? "number" : "text"}
                                min={condInfo.value_type === "number" ? "1" : undefined}
                                value={cond.condition_value || ""}
                                onChange={(e) => updateCondition(idx, "condition_value", e.target.value)}
                                className="h-8 text-sm"
                                placeholder={condInfo.value_type === "number" ? "3" : "value"}
                              />
                            </div>
                          )}
                          <div>
                            <Label className="text-xs">Priority</Label>
                            <Input
                              type="number"
                              min="1"
                              max="100"
                              value={cond.priority}
                              onChange={(e) => updateCondition(idx, "priority", parseInt(e.target.value) || 50)}
                              className="h-8 text-sm"
                            />
                            <p className="text-[10px] text-muted-foreground mt-0.5">
                              Lower = checked first. 100 = fallback
                            </p>
                          </div>
                        </div>
                        <div>
                          <Label className="text-xs">Description Template</Label>
                          <Input
                            value={cond.template}
                            onChange={(e) => updateCondition(idx, "template", e.target.value)}
                            placeholder="{team_name} plays {opponent} at {venue}"
                            className="font-mono text-sm"
                          />
                          {cond.template && (
                            <div className="mt-1 px-2 py-1 bg-secondary/50 border-l-2 border-primary rounded-sm">
                              <span className="text-[10px] text-muted-foreground uppercase font-semibold mr-2">Preview:</span>
                              <span className="text-sm italic">{resolveTemplate(cond.template)}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Load Preset Dialog */}
      <Dialog open={showPresetDialog} onOpenChange={setShowPresetDialog}>
        <DialogContent className="max-w-lg" onClose={() => setShowPresetDialog(false)}>
          <DialogHeader>
            <DialogTitle>Load Preset</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {presetsLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : !presets || presets.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No presets saved yet. Create conditions and save them as a preset.
              </p>
            ) : (
              presets.map((preset) => (
                <div key={preset.id} className="p-3 border rounded-lg hover:bg-secondary/50 transition-colors">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h4 className="font-medium">{preset.name}</h4>
                      {preset.description && (
                        <p className="text-xs text-muted-foreground">{preset.description}</p>
                      )}
                      <p className="text-xs text-muted-foreground mt-1">
                        {preset.conditions.length} condition{preset.conditions.length !== 1 ? "s" : ""}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => applyPreset(preset)}>
                        Apply
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDeletePreset(preset)}
                        disabled={deletePresetMutation.isPending}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPresetDialog(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Save Preset Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent onClose={() => setShowSaveDialog(false)}>
          <DialogHeader>
            <DialogTitle>Save as Preset</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="preset-name">Name *</Label>
              <Input
                id="preset-name"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
                placeholder="e.g., NBA Home Games"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="preset-description">Description</Label>
              <Input
                id="preset-description"
                value={presetDescription}
                onChange={(e) => setPresetDescription(e.target.value)}
                placeholder="Optional description"
              />
            </div>
            <p className="text-sm text-muted-foreground">
              This will save {conditions.length} condition{conditions.length !== 1 ? "s" : ""} as a reusable preset.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
            <SaveButton onClick={handleSavePreset} pending={createPresetMutation.isPending}>
              Save Preset
            </SaveButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
