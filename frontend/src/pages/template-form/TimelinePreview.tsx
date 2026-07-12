import { CalendarClock } from "lucide-react"
import { CollapsibleSection } from "@/components/ui/collapsible-section"

interface FillerBlock {
  enabled: boolean
  title: string
}

interface TimelinePreviewProps {
  isTeamTemplate: boolean
  pregame: FillerBlock
  event: { title: string; subtitle: string }
  postgame: FillerBlock
  /** Team templates only — the between-game-days row. */
  idle: FillerBlock | null
  /** Resolved event start time (e.g. "7:30 PM") labeling the event block. */
  eventTimeLabel: string
  /** Human description of the event block's duration source. */
  durationLabel: string
}

/**
 * EPG-style timeline preview (#416, yk4j.16): the template's registers laid
 * out as a horizontal guide row — pre-game / event / post-game blocks with
 * their server-resolved titles — plus, for team templates, a second row for
 * the idle filler between game days. Widths are representative, not
 * minute-accurate: real filler spans are lifecycle-driven (filler tiles the
 * gap from channel creation to event start), which the client can't know.
 * Disabled fillers render as ghost blocks so the state stays explicit.
 */
export function TimelinePreview({
  isTeamTemplate,
  pregame,
  event,
  postgame,
  idle,
  eventTimeLabel,
  durationLabel,
}: TimelinePreviewProps) {
  return (
    <CollapsibleSection
      title="EPG Timeline"
      icon={<CalendarClock className="h-4 w-4" />}
      variant="subsection"
      persistKey="template-builder.timeline"
      defaultCollapsed={false}
      className="mb-4"
    >
      <div className="space-y-1.5">
        {/* Event-day row */}
        <div className="flex gap-1 items-stretch">
          <FillerCell block={pregame} label="Pre-game" className="flex-[1.2]" />
          <div className="flex-[3] min-w-0 rounded-md border border-border bg-secondary/40 border-l-4 border-l-primary px-3 py-1.5">
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center justify-between gap-2">
              <span>{eventTimeLabel || "Event"}</span>
              <span className="normal-case tracking-normal">{durationLabel}</span>
            </div>
            <div
              className={`text-sm font-semibold leading-snug truncate ${event.title ? "" : "text-muted-foreground italic font-normal"}`}
            >
              {event.title || "(no title)"}
            </div>
            <div className="text-xs text-muted-foreground leading-snug truncate">
              {event.subtitle}
            </div>
          </div>
          <FillerCell block={postgame} label="Post-game" className="flex-[1.2]" />
        </div>

        {/* Team channels live on between game days — show the idle register */}
        {isTeamTemplate && idle && (
          <FillerCell
            block={idle}
            label="Idle · between game days"
            className="w-full"
            tall
          />
        )}
      </div>
    </CollapsibleSection>
  )
}

function FillerCell({
  block,
  label,
  className,
  tall = false,
}: {
  block: FillerBlock
  label: string
  className?: string
  tall?: boolean
}) {
  if (!block.enabled) {
    return (
      <div
        className={`min-w-0 rounded-md border border-dashed border-border/60 px-3 py-1.5 flex flex-col justify-center ${className ?? ""}`}
      >
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">
          {label}
        </div>
        <div className="text-xs text-muted-foreground/60 italic">off</div>
      </div>
    )
  }
  return (
    <div
      className={`min-w-0 rounded-md border border-border bg-secondary/20 px-3 py-1.5 ${className ?? ""}`}
    >
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={`text-xs leading-snug ${tall ? "" : "line-clamp-2"} ${block.title ? "text-foreground/80" : "text-muted-foreground/60 italic"}`}
      >
        {block.title || "(no title)"}
      </div>
    </div>
  )
}
