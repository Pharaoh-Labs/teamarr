import { useEffect, useRef, useState } from "react"
import {
  previewTemplate,
  type ConditionalDescription,
  type ConditionalPreview,
  type TemplateCreate,
} from "@/api/templates"

export interface ServerPreview {
  /** template string -> server-rendered result (real resolver) */
  rendered: Record<string, string>
  /** Trace for the form's conditional descriptions: which row fires and why */
  conditional: ConditionalPreview | null
  /** Whether the server rendered against a real live event */
  isLive: boolean
}

const DEBOUNCE_MS = 400

/**
 * Debounced server-side render (#357). Sends every unique template string on
 * the form keyed by its own text, so results cache per template text and the
 * `resolveTemplate(value)` call sites need no knowledge of field names. The
 * client-side regex resolver stays as the instant optimistic layer; the
 * server render overrides it as truth once it lands.
 */
export function useServerPreview(args: {
  templates: string[]
  conditionalDescriptions: ConditionalDescription[]
  league: string
  live: boolean
  templateType: string
}): ServerPreview {
  const { templates, conditionalDescriptions, league, live, templateType } = args
  const [rendered, setRendered] = useState<Record<string, string>>({})
  const [conditional, setConditional] = useState<ConditionalPreview | null>(null)
  const [isLive, setIsLive] = useState(false)
  const seqRef = useRef(0)

  const uniqueTemplates = Array.from(new Set(templates.filter(Boolean)))
  // Stable change signature so the effect re-fires only on real edits.
  const signature = JSON.stringify([uniqueTemplates, conditionalDescriptions, league, live])

  useEffect(() => {
    const seq = ++seqRef.current
    const timer = setTimeout(async () => {
      const [tmpls, conds, lg, lv] = JSON.parse(signature) as [
        string[],
        ConditionalDescription[],
        string,
        boolean,
      ]
      if (tmpls.length === 0 && conds.length === 0) return
      try {
        const resp = await previewTemplate({
          league: lg,
          live: lv,
          template_type: templateType,
          fields: Object.fromEntries(tmpls.map((t) => [t, t])),
          conditional_descriptions: conds,
        })
        if (seq !== seqRef.current) return // stale response — a newer edit is in flight
        setRendered(resp.fields)
        setConditional(resp.conditional)
        setIsLive(resp.live)
      } catch {
        // Server preview unavailable — the client-side optimistic layer stands.
        if (seq === seqRef.current) {
          setRendered({})
          setConditional(null)
          setIsLive(false)
        }
      }
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [signature, templateType])

  return { rendered, conditional, isLive }
}

/** Every template-bearing string on the form, for the server render sweep. */
export function collectTemplateStrings(form: TemplateCreate): string[] {
  const out: string[] = []
  // Variable-free strings still go through: the engine's cleanup pass (empty
  // parens, space collapse) applies to them too, and fidelity is the point.
  const push = (v: unknown) => {
    if (typeof v === "string" && v.trim() !== "") out.push(v)
  }
  push(form.title_format)
  push(form.subtitle_template)
  push(form.description_template)
  push(form.event_channel_name)
  const groups: (object | null | undefined)[] = [
    form.pregame_fallback,
    form.postgame_fallback,
    form.idle_content,
    form.postgame_conditional,
    form.idle_conditional,
    form.idle_offseason,
  ]
  for (const group of groups) {
    if (group) Object.values(group).forEach(push)
  }
  for (const cond of form.conditional_descriptions ?? []) push(cond.template)
  return out
}
