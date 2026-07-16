/**
 * StreamItem — renders a single stream name with multi-layer regex highlighting.
 *
 * Each extraction field (teams, date, time, league, fighters, event name) gets a distinct color.
 * Include/exclude matches are shown as green borders or red strike-through.
 * Built-in filter matches are shown with filter reason badge.
 */

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import type { MatchRange } from "@/lib/regex-utils"
import type { StreamExtractionResult } from "@/api/groups"

// ---------------------------------------------------------------------------
// Color mapping for extraction fields
// ---------------------------------------------------------------------------

const FIELD_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  team1:  { bg: "bg-blue-500/20",    text: "text-blue-300",    label: "Team 1" },
  team2:  { bg: "bg-cyan-500/20",    text: "text-cyan-300",    label: "Team 2" },
  date:   { bg: "bg-yellow-500/20",  text: "text-yellow-300",  label: "Date" },
  month:  { bg: "bg-yellow-500/15",  text: "text-yellow-200",  label: "Month" },
  day:    { bg: "bg-yellow-500/15",  text: "text-yellow-200",  label: "Day" },
  time:   { bg: "bg-orange-500/20",  text: "text-orange-300",  label: "Time" },
  league: { bg: "bg-purple-500/20",  text: "text-purple-300",  label: "League" },
  // Combat / Event Card extraction
  fighter1:   { bg: "bg-blue-500/20",   text: "text-blue-300",   label: "Fighter 1" },
  fighter2:   { bg: "bg-cyan-500/20",   text: "text-cyan-300",   label: "Fighter 2" },
  fighters:   { bg: "bg-blue-500/20",   text: "text-blue-300",   label: "Fighters" },
  event_name: { bg: "bg-pink-500/20",   text: "text-pink-300",   label: "Event Name" },
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StreamItemProps {
  name: string
  index: number
  /** Ranges to highlight, tagged by group name */
  extractionRanges: MatchRange[]
  /** Whether stream matches the include regex */
  includeMatch: boolean | null // null = no include regex set
  /** Whether stream matches the exclude regex */
  excludeMatch: boolean
  /** Reason stream would be filtered by builtin filters (null if passes) */
  builtinFilterReason: string | null
  /** Pipeline-truth extraction result from the backend (#458); null = not tested */
  pipelineResult: StreamExtractionResult | null
  /** Whether built-in filtering is skipped */
  skipBuiltinFilter: boolean
  /** Called when user selects text for interactive pattern generation */
  onTextSelect?: (text: string, streamName: string) => void
}

// ---------------------------------------------------------------------------
// Segment builder — merge overlapping ranges into render segments
// ---------------------------------------------------------------------------

interface Segment {
  text: string
  groups: string[] // which field groups cover this span
}

function buildSegments(text: string, ranges: MatchRange[]): Segment[] {
  if (ranges.length === 0) {
    return [{ text, groups: [] }]
  }

  // Sort ranges by start position
  const sorted = [...ranges].sort((a, b) => a.start - b.start)

  // Build segments by walking the text character by character
  const segments: Segment[] = []
  let pos = 0

  for (const range of sorted) {
    // Clamp to text bounds
    const start = Math.max(range.start, pos)
    const end = Math.min(range.end, text.length)
    if (start >= end) continue

    // Text before this range
    if (start > pos) {
      segments.push({ text: text.slice(pos, start), groups: [] })
    }

    // The highlighted range
    segments.push({
      text: text.slice(start, end),
      groups: range.group ? [range.group] : [],
    })
    pos = end
  }

  // Remaining text
  if (pos < text.length) {
    segments.push({ text: text.slice(pos), groups: [] })
  }

  return segments
}

/** Format builtin filter reason for display */
function formatFilterReason(reason: string): string {
  if (reason === "placeholder") return "placeholder"
  if (reason === "not_event") return "no event pattern"
  if (reason.startsWith("unsupported_sport:")) {
    return reason.replace("unsupported_sport:", "").toLowerCase()
  }
  return reason
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StreamItem({
  name,
  index,
  extractionRanges,
  pipelineResult,
  includeMatch,
  excludeMatch,
  builtinFilterReason,
  skipBuiltinFilter,
  onTextSelect,
}: StreamItemProps) {
  const segments = useMemo(
    () => buildSegments(name, extractionRanges),
    [name, extractionRanges]
  )

  // When skip is OFF: actually filtered; when skip is ON: just marked (not filtered)
  const isBuiltinFiltered = !skipBuiltinFilter && builtinFilterReason !== null
  const wouldBeBuiltinFiltered = skipBuiltinFilter && builtinFilterReason !== null

  const isExcluded = excludeMatch || isBuiltinFiltered
  const isFilteredByInclude = includeMatch === false // include regex set but doesn't match

  // Pipeline verdict (#458): per enabled field, did the REAL extraction succeed?
  const pipeline = useMemo(() => {
    if (!pipelineResult) return null
    const fields: { label: string; matched: boolean; values: string[] }[] = []
    const push = (label: string, f: { matched: boolean; values: string[] } | null) => {
      if (f) fields.push({ label, ...f })
    }
    push("teams", pipelineResult.teams)
    push("fighters", pipelineResult.fighters)
    push("event", pipelineResult.event_name)
    push("date", pipelineResult.date)
    push("time", pipelineResult.time)
    push("league", pipelineResult.league)
    if (fields.length === 0) return null
    const failed = fields.filter((f) => !f.matched)
    const title = fields
      .map((f) => `${f.label}: ${f.matched ? f.values.join(" vs ") || "✓" : "✗ not extracted"}`)
      .join("\n")
    return { failed, allOk: failed.length === 0, title }
  }, [pipelineResult])

  const handleMouseUp = () => {
    if (!onTextSelect) return
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed) return
    const text = sel.toString().trim()
    if (text.length > 0) {
      onTextSelect(text, name)
    }
  }

  return (
    <div
      className={cn(
        "flex items-start gap-2 px-3 py-1.5 text-xs font-mono border-l-2",
        isExcluded && "opacity-40 line-through border-l-destructive/50",
        isFilteredByInclude && "opacity-40 border-l-muted",
        wouldBeBuiltinFiltered && "opacity-70 border-l-yellow-500/70",
        !isExcluded && !isFilteredByInclude && !wouldBeBuiltinFiltered && includeMatch && "border-l-success/70",
        !isExcluded && !isFilteredByInclude && !wouldBeBuiltinFiltered && includeMatch === null && "border-l-transparent",
      )}
      onMouseUp={handleMouseUp}
    >
      <span className="text-muted-foreground/50 w-8 text-right shrink-0 select-none">
        {index + 1}
      </span>
      <span className="break-all select-text flex-1">
        {segments.map((seg, i) => {
          if (seg.groups.length === 0) {
            return <span key={i}>{seg.text}</span>
          }
          const group = seg.groups[0]
          const color = FIELD_COLORS[group]
          if (!color) {
            return (
              <mark key={i} className="bg-primary/20 text-primary rounded-sm px-0.5">
                {seg.text}
              </mark>
            )
          }
          return (
            <mark
              key={i}
              className={cn(color.bg, color.text, "rounded-sm px-0.5")}
              title={color.label}
            >
              {seg.text}
            </mark>
          )
        })}
      </span>
      {/* Pipeline-truth verdict (#458) — only shown when a pattern is enabled */}
      {pipeline && (
        <span
          className={cn(
            "shrink-0 text-[10px] px-1.5 py-0.5 rounded whitespace-pre",
            pipeline.allOk
              ? "bg-green-500/15 text-green-400"
              : "bg-yellow-500/20 text-yellow-400"
          )}
          title={pipeline.title}
        >
          {pipeline.allOk
            ? "✓ pipeline"
            : `✗ ${pipeline.failed.map((f) => f.label).join(", ")}`}
        </span>
      )}
      {/* Show filter reason badge when stream matches builtin filter */}
      {builtinFilterReason && (
        <span
          className={cn(
            "shrink-0 text-[10px] px-1.5 py-0.5 rounded",
            skipBuiltinFilter
              ? "bg-yellow-500/20 text-yellow-400"
              : "bg-red-500/20 text-red-400"
          )}
          title={skipBuiltinFilter ? "Would be filtered (builtin skipped)" : "Filtered by builtin filter"}
        >
          {formatFilterReason(builtinFilterReason)}
        </span>
      )}
    </div>
  )
}
