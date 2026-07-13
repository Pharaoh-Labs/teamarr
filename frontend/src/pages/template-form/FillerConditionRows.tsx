import { useState } from "react"
import { ChevronRight, Trash2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AutoGrowTextarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import type { ConditionalDescription, ConditionRowTrace } from "@/api/templates"
import { fetchConditions } from "@/api/variables"

interface FillerConditionRowsProps {
  value: ConditionalDescription[]
  onChange: (rows: ConditionalDescription[]) => void
  isTeamTemplate: boolean
  resolveTemplate: (template: string) => string
  /** Which game the register's rows evaluate against ("next game" / "last game"). */
  referenceLabel: string
  /** Server preview trace for these rows (#428): which fired for the preview event. */
  trace?: ConditionRowTrace[]
}

/**
 * Condition-row editor for a filler register (#420, epic cajd).
 *
 * Same row shape and per-field semantics as the Conditions tab
 * (conditional_descriptions): the highest-priority MATCHING row that sets a
 * field wins; unset fields fall through to the register's base content, and
 * a winning description that resolves empty cascades to the next matching
 * row, then the base. Rows evaluate against the register's reference game.
 */
export function FillerConditionRows({
  value,
  onChange,
  isTeamTemplate,
  resolveTemplate,
  referenceLabel,
  trace,
}: FillerConditionRowsProps) {
  const rows = value || []
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const templateType = isTeamTemplate ? "team" : "event"
  const { data: conditionsData } = useQuery({
    queryKey: ["conditions", templateType],
    queryFn: () => fetchConditions(templateType),
    staleTime: 5 * 60 * 1000,
  })
  const availableConditions = conditionsData?.conditions || []
  const conditionInfo = (name: string) => availableConditions.find((c) => c.name === name)

  const addRow = () => {
    // Game-state conditions are the natural filler default; fall back to the
    // first available condition if the API list hasn't loaded yet.
    const preferred = ["is_final", "is_not_final", "has_recap"].find((n) => conditionInfo(n))
    const condition = preferred || availableConditions[0]?.name || "is_final"
    onChange([...rows, { condition, template: "", priority: 50 }])
    setExpanded((prev) => new Set([...prev, rows.length]))
  }

  const updateRow = (index: number, field: keyof ConditionalDescription, val: string | number) => {
    const updated = [...rows]
    updated[index] = { ...updated[index], [field]: val }
    onChange(updated)
  }

  const removeRow = (index: number) => {
    onChange(rows.filter((_, i) => i !== index))
    setExpanded((prev) => {
      const shifted = new Set<number>()
      prev.forEach((i) => {
        if (i === index) return
        shifted.add(i > index ? i - 1 : i)
      })
      return shifted
    })
  }

  const toggleExpanded = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const sorted = [...rows]
    .map((r, i) => ({ ...r, originalIndex: i }))
    .sort((a, b) => a.priority - b.priority)

  return (
    <div className="p-3 bg-secondary/30 rounded-lg space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Condition rows</span>
        <Button onClick={addRow} variant="outline" size="sm">
          + Add Row
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Evaluated against the {referenceLabel}. Per field, the highest-priority matching row
        wins; anything a row doesn't set falls back to the content above. A winning
        description that resolves empty (e.g. {"{game_recap}"} before the provider publishes
        one) cascades to the next matching row, then the base description.
      </p>

      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">
          No rows — the base content above always renders.
        </p>
      ) : (
        <div className="space-y-2">
          {sorted.map((row) => {
            const idx = row.originalIndex
            const isExpanded = expanded.has(idx)
            const info = conditionInfo(row.condition)

            return (
              <div key={idx} className="border rounded-lg overflow-hidden bg-background/50">
                <div
                  className="flex items-center gap-2 p-2 cursor-pointer hover:bg-secondary/50"
                  onClick={() => toggleExpanded(idx)}
                >
                  <ChevronRight
                    className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  />
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-primary/20 text-primary">
                    P{row.priority}
                  </span>
                  <span className="text-sm font-medium flex-1">
                    {info?.description || row.condition}
                    {row.condition_value && ` (${row.condition_value})`}
                  </span>
                  {(row.title || row.subtitle) && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-violet-500/20 text-violet-400"
                      title={`Also overrides ${[row.title && "title", row.subtitle && "subtitle"].filter(Boolean).join(" + ")}`}
                    >
                      {[row.title && "T", row.subtitle && "S"].filter(Boolean).join("·")}
                    </span>
                  )}
                  {(() => {
                    const rowTrace = trace?.find((t) => t.index === idx)
                    const fired = rowTrace?.selected_for?.length
                      ? rowTrace.selected_for
                      : rowTrace?.selected
                        ? ["description"]
                        : []
                    if (fired.length > 0)
                      return (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-400"
                          title={rowTrace?.reason}
                        >
                          fires
                        </span>
                      )
                    if (rowTrace?.matched)
                      return (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-400"
                          title={rowTrace.reason}
                        >
                          outranked
                        </span>
                      )
                    return null
                  })()}
                  {row.template && (
                    <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                      {row.template.substring(0, 40)}
                      {row.template.length > 40 ? "..." : ""}
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeRow(idx)
                    }}
                    className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>

                {isExpanded && (
                  <div className="p-3 pt-0 space-y-3 border-t">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3">
                      <div>
                        <Label className="text-xs">Condition</Label>
                        <Select
                          value={row.condition}
                          onChange={(e) => updateRow(idx, "condition", e.target.value)}
                          className="h-8 text-sm"
                        >
                          {availableConditions.map((c) => (
                            <option key={c.name} value={c.name}>
                              {c.description}
                              {c.providers === "espn" ? " (ESPN only)" : ""}
                            </option>
                          ))}
                        </Select>
                      </div>
                      {info?.requires_value && (
                        <div>
                          <Label className="text-xs">Value</Label>
                          <Input
                            type={info.value_type === "number" ? "number" : "text"}
                            min={info.value_type === "number" ? "1" : undefined}
                            value={row.condition_value || ""}
                            onChange={(e) => updateRow(idx, "condition_value", e.target.value)}
                            className="h-8 text-sm"
                            placeholder={info.value_type === "number" ? "3" : "value"}
                          />
                        </div>
                      )}
                      <div>
                        <Label className="text-xs">Priority</Label>
                        <Input
                          type="number"
                          min="1"
                          max="100"
                          value={row.priority}
                          onChange={(e) => updateRow(idx, "priority", parseInt(e.target.value) || 50)}
                          className="h-8 text-sm"
                        />
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          Lower = checked first
                        </p>
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs">Description</Label>
                      <AutoGrowTextarea
                        value={row.template}
                        onChange={(e) => updateRow(idx, "template", e.target.value)}
                        placeholder="{game_recap.last}"
                        className="font-mono text-sm"
                      />
                      {row.template && (
                        <div className="mt-1 px-2 py-1 bg-secondary/50 border-l-2 border-primary rounded-sm">
                          <span className="text-[10px] text-muted-foreground uppercase font-semibold mr-2">
                            Preview:
                          </span>
                          <span className="text-sm italic">{resolveTemplate(row.template)}</span>
                        </div>
                      )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <Label className="text-xs">
                          Title Override <span className="text-muted-foreground">(optional)</span>
                        </Label>
                        <Input
                          value={row.title || ""}
                          onChange={(e) => updateRow(idx, "title", e.target.value)}
                          className="font-mono text-sm"
                        />
                      </div>
                      <div>
                        <Label className="text-xs">
                          Subtitle Override <span className="text-muted-foreground">(optional)</span>
                        </Label>
                        <Input
                          value={row.subtitle || ""}
                          onChange={(e) => updateRow(idx, "subtitle", e.target.value)}
                          className="font-mono text-sm"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
