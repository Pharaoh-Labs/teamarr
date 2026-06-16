import { useState, useMemo } from "react"
import { toast } from "sonner"
import { ChevronRight, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { ConditionalDescription } from "@/api/templates"
import { TemplateField } from "../TemplateField"
import type { TabProps } from "../types"

export function DefaultsTab({ formData, setFormData, isTeamTemplate, fieldRefs, setLastFocusedField, resolveTemplate, validationData }: TabProps) {
  const isEventTemplate = !isTeamTemplate
  // Extract fallback descriptions from conditional_descriptions (priority === 100)
  const fallbacks = useMemo(() => {
    const all = formData.conditional_descriptions || []
    return all
      .filter((c) => c.priority === 100)
      .map((c) => ({ label: c.label || "Default", template: c.template }))
  }, [formData.conditional_descriptions])

  // If no fallbacks exist, use description_template as the single fallback
  const effectiveFallbacks = fallbacks.length > 0 ? fallbacks :
    formData.description_template ? [{ label: "Default", template: formData.description_template }] : []

  const [expandedFallbacks, setExpandedFallbacks] = useState<Set<number>>(new Set([0]))

  const addFallback = () => {
    const newLabel = effectiveFallbacks.length === 0 ? "Default" : `Default ${effectiveFallbacks.length + 1}`
    const newFallback: ConditionalDescription = {
      condition: "",
      template: "",
      priority: 100,
      label: newLabel,
    }
    setFormData((prev) => {
      const nonFallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority !== 100)
      return {
        ...prev,
        conditional_descriptions: [...nonFallbacks, ...getFallbacksAsConditions(), newFallback],
        description_template: null,
      }
    })
    setExpandedFallbacks((prev) => new Set([...prev, effectiveFallbacks.length]))
  }

  const getFallbacksAsConditions = (): ConditionalDescription[] => {
    return effectiveFallbacks.map((f) => ({
      condition: "",
      template: f.template,
      priority: 100,
      label: f.label,
    }))
  }

  const updateFallback = (index: number, field: "label" | "template", value: string) => {
    const updated = [...effectiveFallbacks]
    updated[index] = { ...updated[index], [field]: value }
    const fallbackConditions = updated.map((f) => ({
      condition: "",
      template: f.template,
      priority: 100,
      label: f.label,
    }))
    setFormData((prev) => {
      const nonFallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority !== 100)
      return {
        ...prev,
        conditional_descriptions: [...nonFallbacks, ...fallbackConditions],
        description_template: null,
      }
    })
  }

  const removeFallback = (index: number) => {
    if (effectiveFallbacks.length <= 1) {
      toast.error("At least one default description is required")
      return
    }
    const updated = effectiveFallbacks.filter((_, i) => i !== index)
    const fallbackConditions = updated.map((f) => ({
      condition: "",
      template: f.template,
      priority: 100,
      label: f.label,
    }))
    setFormData((prev) => {
      const nonFallbacks = (prev.conditional_descriptions || []).filter((c) => c.priority !== 100)
      return {
        ...prev,
        conditional_descriptions: [...nonFallbacks, ...fallbackConditions],
        description_template: null,
      }
    })
    setExpandedFallbacks((prev) => {
      const next = new Set(prev)
      next.delete(index)
      return next
    })
  }

  const toggleFallback = (index: number) => {
    setExpandedFallbacks((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  return (
    <div className="space-y-6">
      {/* Channel Name & Logo (Event templates only) */}
      {!isTeamTemplate && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Channel Name & Logo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <TemplateField
              id="event_channel_name"
              label="Channel Name Template"
              value={formData.event_channel_name || ""}
              onChange={(v) => setFormData((prev) => ({ ...prev, event_channel_name: v || null }))}
              placeholder="{away_team} @ {home_team}"
              helpText="Name for auto-created Dispatcharr channels"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="event_channel_logo_url"
              isImageField
              label="Channel Logo URL Template"
              value={formData.event_channel_logo_url || ""}
              onChange={(v) => setFormData((prev) => ({ ...prev, event_channel_logo_url: v || null }))}
              placeholder="Optional"
              helpText="Optional. Static URL or template with variables."
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
          </CardContent>
        </Card>
      )}

      {/* Title & Subtitle */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Title & Subtitle</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <TemplateField
            id="title_format"
            label="Program Title Template *"
            value={formData.title_format || ""}
            onChange={(v) => setFormData((prev) => ({ ...prev, title_format: v }))}
            placeholder="{league} {sport}"
            fieldRefs={fieldRefs}
            setLastFocusedField={setLastFocusedField}
            resolveTemplate={resolveTemplate}
            validationData={validationData}
            isEventTemplate={isEventTemplate}
          />
          <TemplateField
            id="subtitle_template"
            label="Program Subtitle Template"
            value={formData.subtitle_template || ""}
            onChange={(v) => setFormData((prev) => ({ ...prev, subtitle_template: v || null }))}
            placeholder="{away_team} at {home_team}"
            fieldRefs={fieldRefs}
            setLastFocusedField={setLastFocusedField}
            resolveTemplate={resolveTemplate}
            validationData={validationData}
            isEventTemplate={isEventTemplate}
          />
        </CardContent>
      </Card>

      {/* Default Descriptions (Multiple with randomization) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Default Description Templates</CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            Used when no conditions match. If multiple defaults exist, one is randomly selected.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {effectiveFallbacks.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No default descriptions yet. Click "Add Default Description" to get started.
            </p>
          ) : (
            effectiveFallbacks.map((fallback, index) => (
              <div key={index} className="border rounded-lg overflow-hidden">
                {/* Header */}
                <div
                  className="flex items-center justify-between px-3 py-2 bg-muted/50 cursor-pointer hover:bg-muted/70"
                  onClick={() => toggleFallback(index)}
                >
                  <div className="flex items-center gap-2">
                    <ChevronRight
                      className={`h-4 w-4 transition-transform ${expandedFallbacks.has(index) ? "rotate-90" : ""}`}
                    />
                    <span className="font-medium text-sm">{fallback.label || "Untitled"}</span>
                    <span className="text-xs text-muted-foreground">(Priority: 100)</span>
                  </div>
                  {effectiveFallbacks.length > 1 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFallback(index)
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                {/* Body */}
                {expandedFallbacks.has(index) && (
                  <div className="p-3 space-y-3 border-t">
                    <div className="space-y-1.5">
                      <Label className="text-sm">Label *</Label>
                      <Input
                        value={fallback.label}
                        onChange={(e) => updateFallback(index, "label", e.target.value)}
                        placeholder="e.g., 'Generic', 'Exciting', 'Classic'"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-sm">Description Template *</Label>
                      <Textarea
                        value={fallback.template}
                        onChange={(e) => updateFallback(index, "template", e.target.value)}
                        placeholder="{matchup} | {venue_full}"
                        rows={3}
                      />
                      {fallback.template && (
                        <p className="text-xs text-muted-foreground">
                          Preview: {resolveTemplate(fallback.template)}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
          <Button variant="outline" size="sm" onClick={addFallback} className="mt-2">
            + Add Default Description
          </Button>
        </CardContent>
      </Card>

      {/* Program Art */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Program Art</CardTitle>
        </CardHeader>
        <CardContent>
          <TemplateField
            id="program_art_url"
            isImageField
            label="Program Art URL Template"
            value={formData.program_art_url || ""}
            onChange={(v) => setFormData((prev) => ({ ...prev, program_art_url: v || null }))}
            placeholder="Optional. Leave blank to disable program art."
            helpText="Optional. Static URL or template with variables."
            fieldRefs={fieldRefs}
            setLastFocusedField={setLastFocusedField}
            resolveTemplate={resolveTemplate}
            validationData={validationData}
            isEventTemplate={isEventTemplate}
          />
        </CardContent>
      </Card>
    </div>
  )
}
