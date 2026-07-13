import { Clock, Tv, Moon } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import type { FillerContent, ConditionalDescription, IdleOffseasonSettings } from "@/api/templates"
import { TemplateField } from "../TemplateField"
import { FillerConditionRows } from "../FillerConditionRows"
import { DEFAULT_PREGAME, DEFAULT_POSTGAME, DEFAULT_IDLE } from "../constants"
import type { TabProps } from "../types"

export function FillersTab({ formData, setFormData, isTeamTemplate, fieldRefs, setLastFocusedField, resolveTemplate, validationData }: TabProps) {
  const isEventTemplate = !isTeamTemplate
  const pregame = formData.pregame_fallback || DEFAULT_PREGAME
  const postgame = formData.postgame_fallback || DEFAULT_POSTGAME
  const idle = formData.idle_content || DEFAULT_IDLE
  const idleOffseason = formData.idle_offseason || { title_enabled: false, title: null, subtitle_enabled: false, subtitle: null, description_enabled: false, description: null }

  const updatePregame = (field: keyof FillerContent, value: string | null) => {
    setFormData((prev) => {
      const current = prev.pregame_fallback || DEFAULT_PREGAME
      return { ...prev, pregame_fallback: { ...current, [field]: value } }
    })
  }

  const updatePostgame = (field: keyof FillerContent, value: string | null) => {
    setFormData((prev) => {
      const current = prev.postgame_fallback || DEFAULT_POSTGAME
      return { ...prev, postgame_fallback: { ...current, [field]: value } }
    })
  }

  const updateIdle = (field: keyof FillerContent, value: string | null) => {
    setFormData((prev) => {
      const current = prev.idle_content || DEFAULT_IDLE
      return { ...prev, idle_content: { ...current, [field]: value } }
    })
  }

  const updateRows = (
    field: "pregame_conditional_rows" | "postgame_conditional_rows" | "idle_conditional_rows",
    rows: ConditionalDescription[],
  ) => {
    setFormData((prev) => ({ ...prev, [field]: rows }))
  }

  const updateIdleOffseason = (field: keyof IdleOffseasonSettings, value: boolean | string | null) => {
    setFormData((prev) => {
      const current = prev.idle_offseason || { title_enabled: false, title: null, subtitle_enabled: false, subtitle: null, description_enabled: false, description: null }
      return { ...prev, idle_offseason: { ...current, [field]: value } }
    })
  }

  return (
    <div className="space-y-6">
      {/* Pregame */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base flex items-center gap-2"><Clock className="h-4 w-4" /> Pregame</CardTitle>
          <Switch
            checked={formData.pregame_enabled ?? true}
            onCheckedChange={(checked) => setFormData((prev) => ({ ...prev, pregame_enabled: checked }))}
          />
        </CardHeader>
        {formData.pregame_enabled && (
          <CardContent className="space-y-4">
            <TemplateField
              id="pregame_fallback.title"
              label="Title"
              value={pregame.title}
              onChange={(v) => updatePregame("title", v)}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="pregame_fallback.subtitle"
              label="Subtitle"
              value={pregame.subtitle || ""}
              onChange={(v) => updatePregame("subtitle", v || null)}
              placeholder="Optional"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="pregame_fallback.description"
              label="Description"
              value={pregame.description}
              onChange={(v) => updatePregame("description", v)}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="pregame_fallback.description_fallback"
              label="Fallback Description"
              value={pregame.description_fallback || ""}
              onChange={(v) => updatePregame("description_fallback", v || null)}
              placeholder="Optional — used when Description resolves empty (e.g. {game_preview} before a preview exists)"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <FillerConditionRows
              value={formData.pregame_conditional_rows || []}
              onChange={(rows) => updateRows("pregame_conditional_rows", rows)}
              isTeamTemplate={!isEventTemplate}
              resolveTemplate={resolveTemplate}
              referenceLabel={isEventTemplate ? "channel's event" : "next game"}
            />
            <TemplateField
              id="pregame_fallback.art_url"
              isImageField
              label="Program Art URL"
              value={pregame.art_url || ""}
              onChange={(v) => updatePregame("art_url", v || null)}
              placeholder="Optional"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
          </CardContent>
        )}
      </Card>

      {/* Postgame */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base flex items-center gap-2"><Tv className="h-4 w-4" /> Postgame</CardTitle>
          <Switch
            checked={formData.postgame_enabled ?? true}
            onCheckedChange={(checked) => setFormData((prev) => ({ ...prev, postgame_enabled: checked }))}
          />
        </CardHeader>
        {formData.postgame_enabled && (
          <CardContent className="space-y-4">
            <TemplateField
              id="postgame_fallback.title"
              label="Title"
              value={postgame.title}
              onChange={(v) => updatePostgame("title", v)}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="postgame_fallback.subtitle"
              label="Subtitle"
              value={postgame.subtitle || ""}
              onChange={(v) => updatePostgame("subtitle", v || null)}
              placeholder="Optional"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
            <TemplateField
              id="postgame_fallback.description"
              label="Description"
              value={postgame.description}
              onChange={(v) => updatePostgame("description", v)}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />

            <FillerConditionRows
              value={formData.postgame_conditional_rows || []}
              onChange={(rows) => updateRows("postgame_conditional_rows", rows)}
              isTeamTemplate={!isEventTemplate}
              resolveTemplate={resolveTemplate}
              referenceLabel={isEventTemplate ? "channel's event (status refreshed)" : "last game (status refreshed)"}
            />

            <TemplateField
              id="postgame_fallback.art_url"
              isImageField
              label="Program Art URL"
              value={postgame.art_url || ""}
              onChange={(v) => updatePostgame("art_url", v || null)}
              placeholder="Optional"
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isEventTemplate={isEventTemplate}
            />
          </CardContent>
        )}
      </Card>

      {/* Idle Day (Team templates only) */}
      {isTeamTemplate && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base flex items-center gap-2"><Moon className="h-4 w-4" /> Idle Day</CardTitle>
            <Switch
              checked={formData.idle_enabled ?? true}
              onCheckedChange={(checked) => setFormData((prev) => ({ ...prev, idle_enabled: checked }))}
            />
          </CardHeader>
          {formData.idle_enabled && (
            <CardContent className="space-y-4">
              {/* Title with offseason override */}
              <TemplateField
                id="idle_content.title"
                label="Title"
                value={idle.title}
                onChange={(v) => updateIdle("title", v)}
                fieldRefs={fieldRefs}
                setLastFocusedField={setLastFocusedField}
                resolveTemplate={resolveTemplate}
              />
              <div className="p-3 bg-secondary/30 rounded-lg space-y-3 -mt-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={idleOffseason.title_enabled}
                    onCheckedChange={() => updateIdleOffseason("title_enabled", !idleOffseason.title_enabled)}
                  />
                  <span className="text-sm">Override title when no games in 30-day lookahead</span>
                </label>
                {idleOffseason.title_enabled && (
                  <TemplateField
                    id="idle_offseason.title"
                    label="No upcoming games:"
                    value={idleOffseason.title || ""}
                    onChange={(v) => updateIdleOffseason("title", v || null)}
                    placeholder="Off-Season Programming"
                    fieldRefs={fieldRefs}
                    setLastFocusedField={setLastFocusedField}
                    resolveTemplate={resolveTemplate}
                  />
                )}
              </div>

              {/* Subtitle with offseason override */}
              <TemplateField
                id="idle_content.subtitle"
                label="Subtitle"
                value={idle.subtitle || ""}
                onChange={(v) => updateIdle("subtitle", v || null)}
                placeholder="Optional"
                fieldRefs={fieldRefs}
                setLastFocusedField={setLastFocusedField}
                resolveTemplate={resolveTemplate}
              />
              <div className="p-3 bg-secondary/30 rounded-lg space-y-3 -mt-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={idleOffseason.subtitle_enabled}
                    onCheckedChange={() => updateIdleOffseason("subtitle_enabled", !idleOffseason.subtitle_enabled)}
                  />
                  <span className="text-sm">Override subtitle when no games in 30-day lookahead</span>
                </label>
                {idleOffseason.subtitle_enabled && (
                  <TemplateField
                    id="idle_offseason.subtitle"
                    label="No upcoming games:"
                    value={idleOffseason.subtitle || ""}
                    onChange={(v) => updateIdleOffseason("subtitle", v || null)}
                    placeholder="See you next season!"
                    fieldRefs={fieldRefs}
                    setLastFocusedField={setLastFocusedField}
                    resolveTemplate={resolveTemplate}
                  />
                )}
              </div>

              {/* Description with offseason override */}
              <TemplateField
                id="idle_content.description"
                label="Description"
                value={idle.description}
                onChange={(v) => updateIdle("description", v)}
                fieldRefs={fieldRefs}
                setLastFocusedField={setLastFocusedField}
                resolveTemplate={resolveTemplate}
              />
              <div className="p-3 bg-secondary/30 rounded-lg space-y-3 -mt-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={idleOffseason.description_enabled}
                    onCheckedChange={() => updateIdleOffseason("description_enabled", !idleOffseason.description_enabled)}
                  />
                  <span className="text-sm">Override description when no games in 30-day lookahead</span>
                </label>
                {idleOffseason.description_enabled && (
                  <TemplateField
                    id="idle_offseason.description"
                    label="No upcoming games:"
                    value={idleOffseason.description || ""}
                    onChange={(v) => updateIdleOffseason("description", v || null)}
                    placeholder="No upcoming {team_name} games scheduled."
                    fieldRefs={fieldRefs}
                    setLastFocusedField={setLastFocusedField}
                    resolveTemplate={resolveTemplate}
                  />
                )}
              </div>

              <FillerConditionRows
                value={formData.idle_conditional_rows || []}
                onChange={(rows) => updateRows("idle_conditional_rows", rows)}
                isTeamTemplate={!isEventTemplate}
                resolveTemplate={resolveTemplate}
                referenceLabel="last game (status refreshed)"
              />

              <TemplateField
                id="idle_content.art_url"
                isImageField
                label="Program Art URL"
                value={idle.art_url || ""}
                onChange={(v) => updateIdle("art_url", v || null)}
                placeholder="Optional"
                fieldRefs={fieldRefs}
                setLastFocusedField={setLastFocusedField}
                resolveTemplate={resolveTemplate}
              />
            </CardContent>
          )}
        </Card>
      )}
    </div>
  )
}
