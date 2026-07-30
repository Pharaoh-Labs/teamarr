/**
 * TestPatternsModal — regex testing workspace for event groups.
 *
 * Opens a full-screen modal that:
 * 1. Loads all raw streams for the group
 * 2. Mirrors the form's regex fields (skip_builtin, include/exclude, extraction)
 * 3. Shows real-time highlighting on every stream
 * 4. Supports interactive text selection for pattern generation
 * 5. Syncs patterns bidirectionally with the form (reads on open, writes on Apply)
 */

import { useState, useCallback, useEffect, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { getRawStreams, testExtraction } from "@/api/groups"
import type { ExtractionPatterns, StreamExtractionResult } from "@/api/groups"
import { jsToPython } from "@/lib/regex-utils"
import { StreamList } from "./StreamList"
import { PatternPanel } from "./PatternPanel"
import { InteractiveSelector } from "./InteractiveSelector"
import { FlaskConical, LoaderCircle, TriangleAlert } from "lucide-react"

// ---------------------------------------------------------------------------
// Types — shared across child components
// ---------------------------------------------------------------------------

export interface PatternState {
  skip_builtin_filter: boolean
  stream_include_regex: string | null
  stream_include_regex_enabled: boolean
  stream_exclude_regex: string | null
  stream_exclude_regex_enabled: boolean
  // Team vs Team extraction patterns
  custom_regex_teams: string | null
  custom_regex_teams_enabled: boolean
  custom_regex_date: string | null
  custom_regex_date_enabled: boolean
  custom_regex_month: string | null
  custom_regex_month_enabled: boolean
  custom_regex_day: string | null
  custom_regex_day_enabled: boolean
  custom_regex_time: string | null
  custom_regex_time_enabled: boolean
  custom_regex_league: string | null
  custom_regex_league_enabled: boolean
  // Combat / Event Card extraction patterns
  custom_regex_fighters: string | null
  custom_regex_fighters_enabled: boolean
  custom_regex_event_name: string | null
  custom_regex_event_name_enabled: boolean
}

const EMPTY_PATTERNS: PatternState = {
  skip_builtin_filter: false,
  stream_include_regex: null,
  stream_include_regex_enabled: false,
  stream_exclude_regex: null,
  stream_exclude_regex_enabled: false,
  // Team vs Team
  custom_regex_teams: null,
  custom_regex_teams_enabled: false,
  custom_regex_date: null,
  custom_regex_date_enabled: false,
  custom_regex_month: null,
  custom_regex_month_enabled: false,
  custom_regex_day: null,
  custom_regex_day_enabled: false,
  custom_regex_time: null,
  custom_regex_time_enabled: false,
  custom_regex_league: null,
  custom_regex_league_enabled: false,
  // Combat / Event Card
  custom_regex_fighters: null,
  custom_regex_fighters_enabled: false,
  custom_regex_event_name: null,
  custom_regex_event_name_enabled: false,
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TestPatternsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  groupId: number | null
  /** Current form patterns — modal reads these on open */
  initialPatterns?: Partial<PatternState>
  /** Called when user clicks Apply — writes patterns back to form */
  onApply?: (patterns: PatternState) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TestPatternsModal({
  open,
  onOpenChange,
  groupId,
  initialPatterns,
  onApply,
}: TestPatternsModalProps) {
  // Local pattern state — initialized from form, editable in modal
  const [patterns, setPatterns] = useState<PatternState>(EMPTY_PATTERNS)

  // Text selection state for interactive pattern generation
  const [selection, setSelection] = useState<{
    text: string
    streamName: string
  } | null>(null)

  // Sync form → modal when opening. Seeded during render (React's "adjusting
  // state when a prop changes" pattern) — fires on exactly the same trigger as
  // the previous effect: any change to `open` or `initialPatterns`, seeding
  // only while the modal is open, without the extra effect render pass.
  const [syncedSeedProps, setSyncedSeedProps] = useState<{
    open: boolean
    initialPatterns: Partial<PatternState> | undefined
  }>({ open: false, initialPatterns: undefined })
  if (open !== syncedSeedProps.open || initialPatterns !== syncedSeedProps.initialPatterns) {
    setSyncedSeedProps({ open, initialPatterns })
    if (open && initialPatterns) {
      setPatterns({ ...EMPTY_PATTERNS, ...initialPatterns })
    }
  }

  // Fetch raw streams
  const {
    data: streamsData,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["rawStreams", groupId],
    queryFn: () => (groupId ? getRawStreams(groupId) : Promise.reject("No group ID")),
    enabled: open && groupId != null,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })

  const streams = streamsData?.streams ?? []

  // ------------------------------------------------------------------
  // Pipeline-truth extraction (#458): debounce the pattern state, then
  // run the REAL Python extraction functions server-side. JS highlighting
  // stays instant; the backend verdict arrives ~half a second later.
  // ------------------------------------------------------------------
  const [debouncedPatterns, setDebouncedPatterns] = useState(patterns)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedPatterns(patterns), 500)
    return () => clearTimeout(t)
  }, [patterns])

  const extractionRequest: ExtractionPatterns | null = useMemo(() => {
    const p = debouncedPatterns
    const anyEnabled =
      (p.custom_regex_teams_enabled && p.custom_regex_teams) ||
      (p.custom_regex_date_enabled && p.custom_regex_date) ||
      (p.custom_regex_month_enabled && p.custom_regex_month) ||
      (p.custom_regex_day_enabled && p.custom_regex_day) ||
      (p.custom_regex_time_enabled && p.custom_regex_time) ||
      (p.custom_regex_league_enabled && p.custom_regex_league) ||
      (p.custom_regex_fighters_enabled && p.custom_regex_fighters) ||
      (p.custom_regex_event_name_enabled && p.custom_regex_event_name)
    if (!anyEnabled) return null
    // The form (and this modal) hold patterns in JS syntax — convert to
    // Python before the backend compiles them with `re` (#494), exactly
    // like the form's save path does.
    const py = (s: string | null) => (s ? jsToPython(s) : s)
    return {
      teams_pattern: py(p.custom_regex_teams),
      teams_enabled: p.custom_regex_teams_enabled,
      date_pattern: py(p.custom_regex_date),
      date_enabled: p.custom_regex_date_enabled,
      month_pattern: py(p.custom_regex_month),
      month_enabled: p.custom_regex_month_enabled,
      day_pattern: py(p.custom_regex_day),
      day_enabled: p.custom_regex_day_enabled,
      time_pattern: py(p.custom_regex_time),
      time_enabled: p.custom_regex_time_enabled,
      league_pattern: py(p.custom_regex_league),
      league_enabled: p.custom_regex_league_enabled,
      fighters_pattern: py(p.custom_regex_fighters),
      fighters_enabled: p.custom_regex_fighters_enabled,
      event_name_pattern: py(p.custom_regex_event_name),
      event_name_enabled: p.custom_regex_event_name_enabled,
    }
  }, [debouncedPatterns])

  const { data: extractionData, isFetching: extractionLoading } = useQuery({
    queryKey: ["testExtraction", groupId, extractionRequest],
    queryFn: () =>
      testExtraction(
        streams.map((s) => s.stream_name),
        extractionRequest!
      ),
    enabled: open && extractionRequest !== null && streams.length > 0,
    staleTime: 5 * 60 * 1000,
    placeholderData: (prev) => prev, // keep old verdicts while retesting
  })

  const pipelineResults = useMemo(() => {
    const map = new Map<string, StreamExtractionResult>()
    if (extractionRequest !== null && extractionData) {
      for (const r of extractionData.results) map.set(r.stream_name, r)
    }
    return map
  }, [extractionData, extractionRequest])

  const patternErrors = extractionRequest !== null
    ? extractionData?.pattern_errors ?? {}
    : {}
  const learnedDateFormat = extractionRequest !== null
    ? extractionData?.learned_date_format ?? null
    : null
  const pipelineWarnings = extractionRequest !== null
    ? extractionData?.warnings ?? []
    : []

  const handlePatternChange = useCallback((update: Partial<PatternState>) => {
    setPatterns((prev) => ({ ...prev, ...update }))
  }, [])

  const handleTextSelect = useCallback(
    (text: string, streamName: string) => {
      setSelection({ text, streamName })
    },
    []
  )

  const handleApply = useCallback(() => {
    onApply?.(patterns)
    onOpenChange(false)
  }, [patterns, onApply, onOpenChange])

  const handleClose = useCallback(() => {
    setSelection(null)
    onOpenChange(false)
  }, [onOpenChange])

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-6xl h-[85vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-4 py-3 border-b border-border shrink-0">
          <DialogTitle className="flex items-center gap-2 text-sm">
            <FlaskConical className="h-4 w-4" />
            Test Patterns
            {streamsData && (
              <span className="text-muted-foreground font-normal">
                — {streamsData.group_name}
              </span>
            )}
          </DialogTitle>
          <DialogDescription className="text-xs">
            Test regex patterns against real streams. Select text in a stream name to generate patterns.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-1 min-h-0">
          {/* Left: Pattern panel */}
          <div className="w-96 shrink-0 border-r border-border overflow-y-auto">
            <PatternPanel patterns={patterns} onChange={handlePatternChange} />
          </div>

          {/* Right: Stream list */}
          <div className="flex-1 flex flex-col min-w-0">
            {isLoading && (
              <div className="flex-1 flex items-center justify-center">
                <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" />
                <span className="ml-2 text-sm text-muted-foreground">
                  Loading streams...
                </span>
              </div>
            )}

            {error && (
              <div className="flex-1 flex items-center justify-center">
                <span className="text-sm text-destructive">
                  Failed to load streams. Make sure the group has an M3U source configured.
                </span>
              </div>
            )}

            {!isLoading && !error && streams.length === 0 && (
              <div className="flex-1 flex items-center justify-center">
                <span className="text-sm text-muted-foreground">
                  No streams found for this group.
                </span>
              </div>
            )}

            {learnedDateFormat && (
              <div className="px-3 py-1 text-xs border-b border-border bg-secondary/30 text-muted-foreground">
                Learned date format from these streams: <code className="px-1 rounded bg-muted">{learnedDateFormat}</code>
                {" "}— applied to every stream. Label pieces with (?P&lt;day&gt;…)(?P&lt;month&gt;…)(?P&lt;year&gt;…) to declare it explicitly.
              </div>
            )}
            {(Object.keys(patternErrors).length > 0 || pipelineWarnings.length > 0) && (
              <div className="px-3 py-1.5 text-xs border-b border-border bg-yellow-500/10 space-y-0.5">
                {Object.entries(patternErrors).map(([field, err]) => (
                  <div key={field} className="text-destructive flex items-center gap-1.5">
                    <TriangleAlert className="h-3 w-3 shrink-0" />
                    <span><span className="font-semibold">{field}</span> pattern is invalid in Python: {err}</span>
                  </div>
                ))}
                {pipelineWarnings.map((w, i) => (
                  <div key={i} className="text-yellow-500 flex items-center gap-1.5">
                    <TriangleAlert className="h-3 w-3 shrink-0" />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            )}

            {!isLoading && !error && streams.length > 0 && (
              <StreamList
                streams={streams}
                patterns={patterns}
                pipelineResults={pipelineResults}
                pipelineLoading={extractionLoading}
                onTextSelect={handleTextSelect}
              />
            )}

            {/* Interactive selector bar */}
            <InteractiveSelector
              selection={selection}
              onClear={() => setSelection(null)}
              onApplyPattern={handlePatternChange}
            />
          </div>
        </div>

        <DialogFooter className="px-4 py-3 border-t border-border shrink-0">
          <div className="flex items-center justify-between w-full">
            <span className="text-xs text-muted-foreground">
              Highlighting is client-side JavaScript regex; the ✓/✗ badges are
              the real Python extraction pipeline. Named groups accept both
              (?&lt;name&gt;...) and Python&apos;s (?P&lt;name&gt;...).
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleClose}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleApply}>
                Apply to Form
              </Button>
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
