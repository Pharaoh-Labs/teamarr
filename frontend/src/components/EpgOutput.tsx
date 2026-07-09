import { useState, useMemo, useRef, useCallback } from "react"
import { Loader2, CheckCircle, AlertTriangle, Search, Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Input } from "@/components/ui/input"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Alert } from "@/components/ui/alert"
import { useEPGAnalysis, useEPGContent } from "@/hooks/useEPG"

function formatBytes(bytes: number | undefined | null): string {
  if (bytes == null || isNaN(bytes) || bytes === 0) return "0 B"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * XML Preview — a top-level collapsible section on the Dashboard. Contains the
 * EPG analysis (coverage gaps / unreplaced-variable issues, or an all-clear)
 * and a searchable preview of the generated XMLTV. The EPG URL lives in the
 * Dashboard status strip; composition counts live on their home tabs / in the
 * run-history table (dropped here per the 7rfd redesign).
 */
export function EpgOutput() {
  const { data: analysis, isLoading: analysisLoading } = useEPGAnalysis()
  const { data: epgContent, isLoading: contentLoading } = useEPGContent(0) // 0 = no limit

  const [searchTerm, setSearchTerm] = useState("")
  const [currentMatch, setCurrentMatch] = useState(0)
  const [showLineNumbers, setShowLineNumbers] = useState(true)
  const previewRef = useRef<HTMLPreElement>(null)

  // Gap highlighting state
  const [highlightedGap, setHighlightedGap] = useState<{
    afterStop: string
    beforeStart: string
    afterProgram: string
    beforeProgram: string
  } | null>(null)

  const epgXml = epgContent?.content

  // Search functionality for XML preview
  const searchMatches = useMemo(() => {
    if (!searchTerm || !epgXml) return []
    const matches: number[] = []
    const lines = epgXml.split("\n")
    const searchLower = searchTerm.toLowerCase()
    lines.forEach((line, idx) => {
      if (line.toLowerCase().includes(searchLower)) {
        matches.push(idx)
      }
    })
    return matches
  }, [searchTerm, epgXml])

  const scrollToMatch = useCallback((matchIndex: number) => {
    if (!previewRef.current || searchMatches.length === 0) return
    const lineNumber = searchMatches[matchIndex]
    const lineHeight = 20
    previewRef.current.scrollTop = lineNumber * lineHeight - 100
  }, [searchMatches])

  const nextMatch = () => {
    if (searchMatches.length === 0) return
    const next = (currentMatch + 1) % searchMatches.length
    setCurrentMatch(next)
    scrollToMatch(next)
  }

  const prevMatch = () => {
    if (searchMatches.length === 0) return
    const prev = (currentMatch - 1 + searchMatches.length) % searchMatches.length
    setCurrentMatch(prev)
    scrollToMatch(prev)
  }

  // Highlighted XML content
  const highlightedContent = useMemo(() => {
    if (!epgXml) return ""
    const lines = epgXml.split("\n")

    if (highlightedGap) {
      const result: string[] = []
      let inProgramme = false
      let programmeLines: number[] = []
      let programmeType: "before" | "after" | null = null

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        const lineNum = showLineNumbers ? `${(i + 1).toString().padStart(4)} | ` : ""

        if (line.includes("<programme")) {
          if (line.includes(`stop="${highlightedGap.afterStop}"`)) {
            inProgramme = true
            programmeType = "before"
            programmeLines = [i]
          } else if (line.includes(`start="${highlightedGap.beforeStart}"`)) {
            inProgramme = true
            programmeType = "after"
            programmeLines = [i]
          }
        }

        if (inProgramme) {
          if (!programmeLines.includes(i)) {
            programmeLines.push(i)
          }
        }

        if (inProgramme && line.includes("</programme>")) {
          inProgramme = false
          const bgClass = programmeType === "before"
            ? "bg-red-400/30"
            : "bg-blue-400/30"

          for (const lineIdx of programmeLines) {
            const ln = showLineNumbers ? `${(lineIdx + 1).toString().padStart(4)} | ` : ""
            result.push(`<span class="${bgClass}">${ln}${escapeHtml(lines[lineIdx])}</span>`)
          }
          programmeLines = []
          programmeType = null
          continue
        }

        if (!inProgramme) {
          result.push(`${lineNum}${escapeHtml(line)}`)
        }
      }
      return result.join("\n")
    }

    return lines.map((line, idx) => {
      const lineNum = showLineNumbers ? `${(idx + 1).toString().padStart(4)} | ` : ""
      const isMatch = searchTerm && line.toLowerCase().includes(searchTerm.toLowerCase())
      const isCurrentMatch = isMatch && searchMatches[currentMatch] === idx

      if (isCurrentMatch) {
        return `<span class="bg-yellow-500/40">${lineNum}${escapeHtml(line)}</span>`
      } else if (isMatch) {
        return `<span class="bg-yellow-500/20">${lineNum}${escapeHtml(line)}</span>`
      }
      return `${lineNum}${escapeHtml(line)}`
    }).join("\n")
  }, [epgXml, showLineNumbers, searchTerm, currentMatch, searchMatches, highlightedGap])

  const hasIssues = (analysis?.unreplaced_variables?.length ?? 0) > 0 ||
                   (analysis?.coverage_gaps?.length ?? 0) > 0

  return (
    <CollapsibleSection
      title="XML Preview"
      icon={<Terminal className="h-4 w-4 text-muted-foreground" />}
      persistKey="epg-xml-preview"
      count={epgContent ? `${epgContent.total_lines} lines · ${formatBytes(epgContent.size_bytes)}` : undefined}
    >
      <div className="space-y-2">
        {/* EPG analysis: issues or all-clear */}
        {analysisLoading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : analysis && hasIssues ? (
          <Alert
            variant="warning"
            className="space-y-2"
            icon={<AlertTriangle className="h-4 w-4" />}
            title="Detected Issues"
          >
            {analysis.unreplaced_variables.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-1">
                  Unreplaced Variables ({analysis.unreplaced_variables.length})
                </div>
                <div className="flex flex-wrap gap-1">
                  {analysis.unreplaced_variables.map((v) => (
                    <code
                      key={v}
                      className="text-xs bg-yellow-500/20 px-1.5 py-0.5 rounded cursor-pointer hover:bg-yellow-500/40"
                      onClick={() => setSearchTerm(v)}
                    >
                      {v}
                    </code>
                  ))}
                </div>
              </div>
            )}

            {analysis.coverage_gaps.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-1">
                  Coverage Gaps ({analysis.coverage_gaps.length})
                </div>
                <div className="space-y-1 max-h-32 overflow-y-auto">
                  {analysis.coverage_gaps.slice(0, 10).map((gap, idx) => (
                    <div
                      key={idx}
                      className="text-xs bg-yellow-500/20 px-2 py-1 rounded cursor-pointer hover:bg-yellow-500/40"
                      onClick={() => {
                        setSearchTerm("")
                        setHighlightedGap({
                          afterStop: gap.after_stop,
                          beforeStart: gap.before_start,
                          afterProgram: gap.after_program,
                          beforeProgram: gap.before_program,
                        })
                        setTimeout(() => {
                          if (previewRef.current) {
                            const mark = previewRef.current.querySelector(".bg-red-400\\/30, .bg-blue-400\\/30")
                            if (mark) {
                              mark.scrollIntoView({ behavior: "smooth", block: "center" })
                            }
                          }
                        }, 100)
                      }}
                    >
                      <strong>{gap.channel}</strong>: {gap.gap_minutes}min gap between "{gap.after_program}" and "{gap.before_program}"
                    </div>
                  ))}
                  {analysis.coverage_gaps.length > 10 && (
                    <div className="text-xs text-muted-foreground">
                      ... and {analysis.coverage_gaps.length - 10} more
                    </div>
                  )}
                </div>
              </div>
            )}
          </Alert>
        ) : analysis ? (
          <Alert
            variant="success"
            icon={<CheckCircle className="h-4 w-4" />}
            title="No Issues Detected"
          >
            <p className="text-xs text-muted-foreground">
              All template variables resolved and no coverage gaps found.
            </p>
          </Alert>
        ) : null}

        {/* XML content */}
        {contentLoading ? (
          <Spinner />
        ) : epgContent?.content ? (
          <div className="space-y-2">
            {/* Search Bar */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search XML..."
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value)
                    setCurrentMatch(0)
                    setHighlightedGap(null)
                  }}
                  className="pl-8"
                />
              </div>
              {highlightedGap && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-yellow-600">
                    Gap: "{highlightedGap.afterProgram}" → "{highlightedGap.beforeProgram}"
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setHighlightedGap(null)}
                    className="h-6 px-2 text-xs"
                  >
                    Clear
                  </Button>
                </div>
              )}
              {searchMatches.length > 0 && !highlightedGap && (
                <div className="flex items-center gap-1">
                  <span className="text-sm text-muted-foreground">
                    {currentMatch + 1}/{searchMatches.length}
                  </span>
                  <Button variant="outline" size="sm" onClick={prevMatch}>
                    Prev
                  </Button>
                  <Button variant="outline" size="sm" onClick={nextMatch}>
                    Next
                  </Button>
                </div>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowLineNumbers(!showLineNumbers)}
              >
                {showLineNumbers ? "Hide" : "Show"} Lines
              </Button>
            </div>

            {/* XML Content */}
            <pre
              ref={previewRef}
              className="bg-muted/50 rounded-lg p-4 text-xs font-mono overflow-auto max-h-[600px]"
              dangerouslySetInnerHTML={{ __html: highlightedContent }}
            />
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            No XML content available. Generate EPG first.
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

// Helper function to escape HTML
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}
