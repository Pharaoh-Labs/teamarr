import { Tv, Target } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface GuideCardPreviewProps {
  /** Resolved programme fields — what the viewer's guide would actually show. */
  title: string
  subtitle: string
  description: string
  /** Fields whose value came from a conditional row winning (#370p2). */
  conditionalFields: string[]
}

// Tiny marker on fields whose value a conditional row won for the preview event.
function ConditionalMark({ field }: { field: string }) {
  return (
    <Target
      className="inline h-3 w-3 text-emerald-400 shrink-0"
      aria-label={`${field} set by a conditional rule`}
    />
  )
}

/**
 * EPG-style guide card (yk4j.10): renders the template's title/subtitle/
 * description exactly as a viewer's guide would show them for the current
 * preview event — server-truth values including conditional winners, mirroring
 * generation's precedence (a winning conditional row beats the default field).
 */
export function GuideCardPreview({
  title,
  subtitle,
  description,
  conditionalFields,
}: GuideCardPreviewProps) {
  const won = new Set(conditionalFields)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Tv className="h-4 w-4" /> Guide Preview
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="rounded-md border border-border bg-secondary/40 border-l-4 border-l-primary px-3 py-2.5 space-y-1">
          <div className="flex items-start gap-1.5">
            <span className={`text-sm font-semibold leading-snug ${title ? "" : "text-muted-foreground italic font-normal"}`}>
              {title || "(no title)"}
            </span>
            {won.has("title") && <ConditionalMark field="Title" />}
          </div>
          <div className="flex items-start gap-1.5">
            <span className={`text-xs leading-snug ${subtitle ? "text-muted-foreground" : "text-muted-foreground/60 italic"}`}>
              {subtitle || "(no subtitle)"}
            </span>
            {won.has("subtitle") && <ConditionalMark field="Subtitle" />}
          </div>
          <div className="flex items-start gap-1.5 pt-1 border-t border-border/60">
            <span className={`text-xs leading-snug line-clamp-5 ${description ? "text-foreground/80" : "text-muted-foreground/60 italic"}`}>
              {description || "(no description)"}
            </span>
            {won.has("description") && <ConditionalMark field="Description" />}
          </div>
        </div>
        {won.size > 0 && (
          <p className="mt-1.5 text-[10px] text-muted-foreground flex items-center gap-1">
            <Target className="h-3 w-3 text-emerald-400" />
            marks fields won by a conditional rule for this event
          </p>
        )}
      </CardContent>
    </Card>
  )
}
