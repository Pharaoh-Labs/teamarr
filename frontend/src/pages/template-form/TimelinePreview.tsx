import { CalendarClock, Target } from "lucide-react"
import { CollapsibleSection } from "@/components/ui/collapsible-section"

interface FillerBlock {
  enabled: boolean
  title: string
  description: string
  /** True when a filler condition row won a field for the preview event (#428). */
  conditional?: boolean
}

interface TimelinePreviewProps {
  isTeamTemplate: boolean
  /** Resolved channel name — the guide's left-hand channel cell. */
  channelName: string
  pregame: FillerBlock
  event: {
    title: string
    subtitle: string
    description: string
    /** Fields a conditional row won for the preview event (badge parity, #428). */
    conditionalFields?: string[]
  }
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
  channelName,
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
      <div className="flex gap-1 items-stretch">
        {/* Channel cell — spans both rows, like a real guide's left column.
            Distinct treatment: it's the channel's identity, not a programme. */}
        <div className="w-36 shrink-0 rounded-md border border-primary/50 bg-primary/10 px-3 py-1.5 flex flex-col justify-center">
          <div className="text-[10px] uppercase tracking-wide text-primary/70">
            Channel
          </div>
          <div
            className={`text-xs font-semibold leading-snug line-clamp-3 ${channelName ? "text-primary" : "text-muted-foreground/60 italic font-normal"}`}
          >
            {channelName || "(unnamed)"}
          </div>
        </div>

        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Event-day row */}
          <div className="flex gap-1 items-stretch">
            <FillerCell block={pregame} label="Pre-game" className="flex-[1.2]" />
            <div className="flex-[3] min-w-0 rounded-md border border-border bg-secondary/40 border-l-4 border-l-primary px-3 py-1.5">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center justify-between gap-2">
                <span className="flex items-center gap-1">
                  <span>{eventTimeLabel || "Event"}</span>
                  {(event.conditionalFields?.length ?? 0) > 0 && (
                    <Target
                      className="inline h-3 w-3 text-emerald-400 shrink-0"
                      aria-label={`Event ${event.conditionalFields!.join("/")} set by a conditional rule`}
                    />
                  )}
                </span>
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
              {event.description && (
                <div className="text-[11px] text-foreground/70 leading-snug line-clamp-2 pt-0.5 border-t border-border/60 mt-0.5">
                  {event.description}
                </div>
              )}
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
      title={tall ? undefined : block.description || undefined}
    >
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
        <span>{label}</span>
        {block.conditional && (
          <Target
            className="inline h-3 w-3 text-emerald-400 shrink-0"
            aria-label={`${label} content set by a condition row`}
          />
        )}
      </div>
      <div
        className={`text-xs leading-snug ${tall ? "" : "line-clamp-2"} ${block.title ? "text-foreground/80" : "text-muted-foreground/60 italic"}`}
      >
        {block.title || "(no title)"}
      </div>
      {tall && block.description && (
        <div className="text-[11px] text-foreground/60 leading-snug line-clamp-2 pt-0.5">
          {block.description}
        </div>
      )}
    </div>
  )
}
