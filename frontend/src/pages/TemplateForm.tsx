import { useState, useRef, useMemo } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { ArrowLeft, User, Tv, ArrowRight } from "lucide-react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { SaveButton } from "@/components/ui/save-button"
import { SubNav } from "@/components/ui/sub-nav"
import {
  getTemplate,
  createTemplate,
  updateTemplate,
  type TemplateCreate,
  type FillerContent,
} from "@/api/templates"
import { fetchVariables, fetchSamples, fetchSampleLeagues } from "@/api/variables"
import { buildValidVariableSet } from "@/utils/templateValidation"
import type { Tab } from "./template-form/types"
import {
  TABS,
  DEFAULT_PREGAME,
  DEFAULT_POSTGAME,
  DEFAULT_IDLE,
  DEFAULT_FORM,
  DEFAULT_SAMPLE_DATA,
  createResolver,
} from "./template-form/constants"
import { VariableSidebar } from "./template-form/VariableSidebar"
import { BasicTab } from "./template-form/tabs/BasicTab"
import { DefaultsTab } from "./template-form/tabs/DefaultsTab"
import { ConditionsTab } from "./template-form/tabs/ConditionsTab"
import { FillersTab } from "./template-form/tabs/FillersTab"
import { XmltvTab } from "./template-form/tabs/XmltvTab"

export function TemplateForm() {
  const { templateId } = useParams<{ templateId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEdit = !!templateId

  const [activeTab, setActiveTab] = useState<Tab>("basic")
  const [formData, setFormData] = useState<TemplateCreate>(DEFAULT_FORM)
  const [lastFocusedField, setLastFocusedField] = useState<string | null>(null)
  const [previewLeague, setPreviewLeague] = useState("nba")
  // Default to live: preview real event data when available (green "Live"
  // indicator), falling back to static samples when there's no event. TSDB
  // leagues read cache-only so this can't hammer the free tier.
  const [liveRequested, setLiveRequested] = useState(true)

  // Refs for template fields
  const fieldRefs = useRef<Record<string, HTMLInputElement | HTMLTextAreaElement | null>>({})

  // Fetch existing template if editing
  const { data: template, isLoading: isLoadingTemplate } = useQuery({
    queryKey: ["template", templateId],
    queryFn: () => getTemplate(Number(templateId)),
    enabled: isEdit,
  })

  // Fetch variables for picker, scoped to the current template type so the
  // picker only surfaces variables valid for this template (team/event).
  const pickerTemplateType: "team" | "event" =
    formData.template_type === "event" ? "event" : "team"
  const { data: variablesData } = useQuery({
    queryKey: ["variables", pickerTemplateType],
    queryFn: () => fetchVariables(pickerTemplateType),
    staleTime: Infinity,
  })

  // Leagues to preview against: all enabled leagues, with the subscribed subset
  // shown by default in the sidebar (search reaches the full list).
  const { data: sampleLeaguesData } = useQuery({
    queryKey: ["sample-leagues"],
    queryFn: fetchSampleLeagues,
    staleTime: 60 * 60 * 1000, // 1 hour
  })
  const previewLeagues = sampleLeaguesData?.leagues ?? []
  const subscribedSlugs = sampleLeaguesData?.subscribed_slugs ?? []

  // Keep the preview league valid against the fetched list. Prefer a subscribed
  // league (nba if subscribed, else the first subscribed), then nba, then the
  // first available league. Adjusted during render (React's "adjusting state
  // when a prop changes" pattern) — the guard is self-correcting: once the
  // league is in the list the branch no longer fires.
  if (previewLeagues.length > 0 && !previewLeagues.some((l) => l.slug === previewLeague)) {
    const subscribed = new Set(subscribedSlugs)
    const fallback =
      (subscribed.has("nba") ? previewLeagues.find((l) => l.slug === "nba") : undefined) ??
      previewLeagues.find((l) => subscribed.has(l.slug)) ??
      previewLeagues.find((l) => l.slug === "nba") ??
      previewLeagues[0]
    setPreviewLeague(fallback.slug)
  }

  // Fetch sample data for preview (league-specific, optionally live)
  const { data: samplesData } = useQuery({
    queryKey: ["samples", previewLeague, liveRequested],
    queryFn: () => fetchSamples(previewLeague, { byLeague: true, live: liveRequested }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Create resolver with current sample data
  const sampleData = samplesData?.samples ?? DEFAULT_SAMPLE_DATA
  const resolveTemplate = createResolver(sampleData)
  const isLivePreview = samplesData?.live ?? false

  // Build validation set from variables data. The optional chain is hoisted
  // out of the memo so the manual dependency matches what the React Compiler
  // infers (preserve-manual-memoization).
  const variableCategories = variablesData?.categories
  const validationData = useMemo(() => {
    if (!variableCategories) {
      return { validNames: new Set<string>(), baseNames: new Set<string>() }
    }
    const { validNames, baseNames } = buildValidVariableSet(variableCategories)
    return { validNames, baseNames }
  }, [variableCategories])

  // Helper to merge filler content with defaults, ensuring no null values
  const mergeFillerContent = (content: FillerContent | null, defaults: FillerContent): FillerContent => {
    if (!content) return defaults
    return {
      title: content.title ?? defaults.title,
      subtitle: content.subtitle ?? defaults.subtitle,
      description: content.description ?? defaults.description,
      art_url: content.art_url ?? defaults.art_url,
    }
  }

  // Populate form from the server template during render (React's "adjusting
  // state when a prop changes" pattern) — re-seeds on every refetch, exactly
  // like the previous effect, without the extra effect render pass.
  const [syncedTemplate, setSyncedTemplate] = useState<typeof template>(undefined)
  if (template && template !== syncedTemplate) {
    setSyncedTemplate(template)
    setFormData({
      name: template.name,
      template_type: template.template_type,
      sport: template.sport,
      league: template.league,
      title_format: template.title_format || "",
      subtitle_template: template.subtitle_template,
      description_template: template.description_template,
      program_art_url: template.program_art_url,
      game_duration_mode: template.game_duration_mode || "sport",
      game_duration_override: template.game_duration_override,
      xmltv_flags: template.xmltv_flags || { new: true, live: false, date: false },
      xmltv_video: template.xmltv_video || { enabled: false, quality: "HDTV" },
      xmltv_categories: template.xmltv_categories || ["Sports"],
      xmltv_filler_categories: template.xmltv_filler_categories || [],
      pregame_enabled: template.pregame_enabled ?? true,
      pregame_fallback: mergeFillerContent(template.pregame_fallback, DEFAULT_PREGAME),
      postgame_enabled: template.postgame_enabled ?? true,
      postgame_fallback: mergeFillerContent(template.postgame_fallback, DEFAULT_POSTGAME),
      postgame_conditional: template.postgame_conditional || { enabled: true, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
      idle_enabled: template.idle_enabled ?? true,
      idle_content: mergeFillerContent(template.idle_content, DEFAULT_IDLE),
      idle_conditional: template.idle_conditional || { enabled: true, title_final: null, title_not_final: null, subtitle_final: null, subtitle_not_final: null, description_final: null, description_not_final: null },
      idle_offseason: template.idle_offseason || { title_enabled: false, title: null, subtitle_enabled: false, subtitle: null, description_enabled: false, description: null },
      conditional_descriptions: template.conditional_descriptions || [],
      event_channel_name: template.event_channel_name,
      event_channel_logo_url: template.event_channel_logo_url,
    })
  }

  const createMutation = useMutation({
    mutationFn: createTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] })
      toast.success(`Created template "${formData.name}"`)
      navigate("/epg/templates")
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to create template")
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: TemplateCreate) => updateTemplate(Number(templateId), data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] })
      queryClient.invalidateQueries({ queryKey: ["template", templateId] })
      toast.success(`Updated template "${formData.name}"`)
      navigate("/epg/templates")
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to update template")
    },
  })

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      toast.error("Name is required")
      setActiveTab("basic")
      return
    }

    if (isEdit) {
      updateMutation.mutate(formData)
    } else {
      createMutation.mutate(formData)
    }
  }

  const insertVariable = (varName: string) => {
    if (!lastFocusedField) return
    const field = fieldRefs.current[lastFocusedField]
    if (!field) return

    const start = field.selectionStart || 0
    const end = field.selectionEnd || 0
    const value = (field as HTMLInputElement).value || ""
    const variable = `{${varName}}`
    const newValue = value.substring(0, start) + variable + value.substring(end)

    // Update the form data based on the field name
    updateFieldValue(lastFocusedField, newValue)

    // Restore focus and cursor position
    setTimeout(() => {
      field.focus()
      const newPos = start + variable.length
      field.setSelectionRange(newPos, newPos)
    }, 0)
  }

  const updateFieldValue = (fieldName: string, value: string) => {
    // Handle nested fields like pregame_fallback.title
    const parts = fieldName.split(".")
    if (parts.length === 1) {
      setFormData((prev) => ({ ...prev, [fieldName]: value }))
    } else if (parts.length === 2) {
      const [parent, child] = parts
      setFormData((prev) => {
        const parentObj = (prev as unknown as Record<string, Record<string, unknown> | null>)[parent]
        return {
          ...prev,
          [parent]: {
            ...parentObj,
            [child]: value,
          },
        }
      })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  if (isEdit && isLoadingTemplate) {
    return (
      <Spinner size="lg" className="py-12" />
    )
  }

  const isTeamTemplate = formData.template_type === "team"

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/epg/templates")}>
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">
                {isEdit ? `Edit Template: ${template?.name}` : "Create Template"}
              </h1>
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                  isTeamTemplate ? "bg-secondary text-secondary-foreground" : "bg-primary/15 text-primary"
                }`}
              >
                {isTeamTemplate ? <User className="h-3 w-3" /> : <Tv className="h-3 w-3" />}
                {isTeamTemplate ? "Team" : "Event"}
              </span>
            </div>
          </div>
        </div>
        <SaveButton onClick={handleSubmit} pending={isPending}>
          Save Template
        </SaveButton>
      </div>

      {/* Template Type Banner (edit mode) */}
      {isEdit && (
        <div className="px-4 py-2 rounded-lg mb-4 flex items-center gap-3 bg-secondary/50 border border-secondary">
          {isTeamTemplate ? <User className="h-5 w-5 shrink-0" /> : <Tv className="h-5 w-5 shrink-0" />}
          <span className="font-semibold">{isTeamTemplate ? "Team Template" : "Event Template"}</span>
          <span className="ml-auto text-xs text-muted-foreground">Type cannot be changed after creation</span>
        </div>
      )}

      {/* Type switch (create mode) — Event is the primary path; team is a secondary opt-in */}
      {!isEdit && (
        <div className="px-4 py-2 rounded-lg mb-4 flex items-center gap-3 bg-secondary/30 border border-border">
          {isTeamTemplate ? <User className="h-5 w-5 shrink-0" /> : <Tv className="h-5 w-5 shrink-0" />}
          <span className="font-semibold">{isTeamTemplate ? "Team Template" : "Event Template"}</span>
          <button
            type="button"
            onClick={() => {
              const nextIsTeam = !isTeamTemplate
              setFormData((prev) => ({ ...prev, template_type: nextIsTeam ? "team" : "event" }))
              // Conditions tab is team-only; avoid landing on a hidden tab.
              if (!nextIsTeam && activeTab === "conditions") setActiveTab("basic")
            }}
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
          >
            {isTeamTemplate ? "Switch to event template" : "Need a team template instead?"}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Tabs - outside grid so picker aligns with content */}
      <SubNav
        className="mb-4"
        value={activeTab}
        onChange={(key) => setActiveTab(key as Tab)}
        items={TABS
          .filter((tab) => tab.id !== "conditions" || isTeamTemplate) // Hide conditions tab for event templates
          .map((tab) => ({
            key: tab.id,
            label: tab.label,
            icon: <tab.icon className="h-4 w-4" />,
          }))}
      />

      {/* Main content with sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3 items-start">
        {/* Form area */}
        <div className="lg:col-span-4">
          {/* Tab content */}
          {activeTab === "basic" && (
            <BasicTab
              formData={formData}
              setFormData={setFormData}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
              isTeamTemplate={isTeamTemplate}
            />
          )}
          {activeTab === "defaults" && (
            <DefaultsTab
              formData={formData}
              setFormData={setFormData}
              isTeamTemplate={isTeamTemplate}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
            />
          )}
          {activeTab === "conditions" && (
            <ConditionsTab
              formData={formData}
              setFormData={setFormData}
              resolveTemplate={resolveTemplate}
              isTeamTemplate={isTeamTemplate}
              validationData={validationData}
            />
          )}
          {activeTab === "fillers" && (
            <FillersTab
              formData={formData}
              setFormData={setFormData}
              isTeamTemplate={isTeamTemplate}
              fieldRefs={fieldRefs}
              setLastFocusedField={setLastFocusedField}
              resolveTemplate={resolveTemplate}
              validationData={validationData}
            />
          )}
          {activeTab === "xmltv" && (
            <XmltvTab formData={formData} setFormData={setFormData} resolveTemplate={resolveTemplate} validationData={validationData} isTeamTemplate={isTeamTemplate} />
          )}
        </div>

        {/* Variable picker sidebar */}
        <div className="lg:col-span-1 sticky top-[4rem]" style={{ height: 'calc(100vh - 4.5rem)' }}>
          <VariableSidebar
            categories={variablesData?.categories || []}
            onInsert={insertVariable}
            lastFocusedField={lastFocusedField}
            isTeamTemplate={isTeamTemplate}
            leagues={previewLeagues}
            subscribedSlugs={subscribedSlugs}
            previewLeague={previewLeague}
            onLeagueChange={setPreviewLeague}
            liveRequested={liveRequested}
            isLive={isLivePreview}
            onToggleLive={() => setLiveRequested((v) => !v)}
            liveCoverage={
              isLivePreview && samplesData?.live_total != null
                ? {
                    populated: samplesData.live_populated ?? 0,
                    total: samplesData.live_total,
                    gaps: samplesData.gaps ?? [],
                  }
                : null
            }
          />
        </div>
      </div>
    </div>
  )
}
