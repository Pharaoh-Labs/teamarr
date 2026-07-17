import { useState, useEffect, useMemo } from "react"
import { Search, X, FileText, User, Tv, Clock, MousePointerClick } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Input } from "@/components/ui/input"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import type { VariableSidebarProps, Variable } from "./types"

// Local storage key for recently used variables
const RECENTLY_USED_KEY = "teamarr_recently_used_vars"

function getRecentlyUsed(): string[] {
  try {
    const stored = localStorage.getItem(RECENTLY_USED_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function addToRecentlyUsed(varName: string) {
  try {
    const recent = getRecentlyUsed().filter((v) => v !== varName)
    recent.unshift(varName)
    localStorage.setItem(RECENTLY_USED_KEY, JSON.stringify(recent.slice(0, 10)))
  } catch {
    // Ignore storage errors
  }
}

// Sample value for a variable's tooltip: exact name first, then any suffixed
// form the samples map carries (e.g. game_time has samples under
// "game_time.next").
function lookupSample(
  samples: Record<string, string> | undefined,
  v: Variable,
): string | null {
  if (!samples) return null
  if (samples[v.name]) return samples[v.name]
  for (const s of v.suffixes) {
    if (s !== "base" && samples[`${v.name}${s}`]) return samples[`${v.name}${s}`]
  }
  return null
}

// Determine suffix class for color coding
function getSuffixClass(suffixes: string[]): string {
  if (suffixes.length === 1) {
    if (suffixes[0] === "base") return "var-base"
    if (suffixes[0] === ".last") return "var-last"
    if (suffixes[0] === ".next") return "var-next"
  } else if (suffixes.length === 2 && suffixes.includes("base") && suffixes.includes(".next")) {
    return "var-next" // base+next = odds variables
  } else if (suffixes.length >= 3) {
    return "var-all" // all three contexts
  }
  return "var-all" // default
}

export function VariableSidebar({
  categories,
  onInsert,
  lastFocusedField,
  isTeamTemplate,
  samples,
}: VariableSidebarProps) {
  const [search, setSearch] = useState("")
  const [expandedCat, setExpandedCat] = useState<string | null>(null)
  const [recentlyUsed, setRecentlyUsed] = useState<string[]>(() => getRecentlyUsed())
  const [suffixPopup, setSuffixPopup] = useState<{ varName: string; suffixes: string[]; x: number; y: number } | null>(null)

  // Build a map of variable name -> variable for quick lookup
  const variableMap = useMemo(() => {
    const map: Record<string, Variable> = {}
    categories.forEach((cat) => {
      cat.variables.forEach((v) => {
        map[v.name] = v
      })
    })
    return map
  }, [categories])

  const filteredCategories = useMemo(() => {
    if (!search.trim()) return categories
    const q = search.toLowerCase()
    return categories
      .map((cat) => ({
        ...cat,
        variables: cat.variables.filter(
          (v) => v.name.toLowerCase().includes(q) || v.description.toLowerCase().includes(q)
        ),
      }))
      .filter((cat) => cat.variables.length > 0)
  }, [categories, search])

  const handleInsert = (varName: string, suffix?: string) => {
    const fullVar = suffix && suffix !== "base" ? `${varName}${suffix}` : varName
    onInsert(fullVar)
    addToRecentlyUsed(fullVar)
    setRecentlyUsed(getRecentlyUsed())
    setSuffixPopup(null)
  }

  const handleVariableClick = (e: React.MouseEvent, v: Variable) => {
    e.stopPropagation() // Prevent immediate close from document handler

    // For event templates or single-suffix variables, insert directly
    if (!isTeamTemplate || v.suffixes.length <= 1) {
      const suffix = v.suffixes.length === 1 && v.suffixes[0] !== "base" ? v.suffixes[0] : undefined
      handleInsert(v.name, suffix)
      return
    }

    // For team templates with multiple suffixes, show popup
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setSuffixPopup({
      varName: v.name,
      suffixes: v.suffixes,
      x: rect.left,
      y: rect.bottom + 4,
    })
  }

  // Close popup when clicking outside
  useEffect(() => {
    if (!suffixPopup) return
    const handleClick = (e: MouseEvent) => {
      // Don't close if clicking inside the popup
      const popup = document.getElementById('suffix-popup')
      if (popup && popup.contains(e.target as Node)) return
      setSuffixPopup(null)
    }
    // Use setTimeout to avoid the click that opened the popup from closing it
    const timer = setTimeout(() => {
      document.addEventListener("click", handleClick)
    }, 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener("click", handleClick)
    }
  }, [suffixPopup])

  const totalVars = categories.reduce((sum, cat) => sum + cat.variables.length, 0)

  return (
    <Card className="h-full overflow-y-auto">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileText className="h-4 w-4" /> Template Variables
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Template type chip — which variable set the picker shows. The
            preview league/live controls live in PreviewControls above the
            tabs (yk4j.10). */}
        <div className="flex items-center gap-2 px-2 py-1.5 bg-secondary/50 rounded text-xs">
          <span className="text-muted-foreground">Showing vars for:</span>
          <span className="inline-flex items-center gap-1 font-semibold text-primary">
            {isTeamTemplate ? <User className="h-3 w-3" /> : <Tv className="h-3 w-3" />}
            {isTeamTemplate ? "Team" : "Event"}
          </span>
        </div>

        {/* Insert affordance: chips are disabled until a field has focus —
            say so instead of silently ignoring clicks (#459). */}
        {!lastFocusedField && (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded border border-dashed border-border text-xs text-muted-foreground">
            <MousePointerClick className="h-3.5 w-3.5 shrink-0" />
            Click into a template field to insert variables
          </div>
        )}

        {/* Suffix Guide (team templates only) */}
        {isTeamTemplate ? (
          <div className="p-2 bg-secondary/30 rounded border border-border text-xs space-y-2">
            <div className="space-y-0.5 text-muted-foreground">
              <div><code className="text-primary font-mono text-[11px]">{"{variable}"}</code> current game OR not game-dependent</div>
              <div><code className="text-primary font-mono text-[11px]">{"{variable.next}"}</code> next game</div>
              <div><code className="text-primary font-mono text-[11px]">{"{variable.last}"}</code> last game</div>
            </div>
            <div className="flex flex-wrap gap-1 pt-1.5 border-t border-border text-[10px]">
              <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-semibold">ALL</span>
              <span className="text-muted-foreground">all contexts •</span>
              <span className="px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400 font-semibold">BASE</span>
              <span className="text-muted-foreground">no suffix •</span>
              <span className="px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 font-semibold">.next</span>
              <span className="text-muted-foreground">base+.next •</span>
              <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-semibold">.last</span>
              <span className="text-muted-foreground">.last only</span>
            </div>
          </div>
        ) : (
          <div className="p-2 bg-secondary/30 rounded text-xs text-muted-foreground">
            Event templates use single-game context. No suffixes needed.
          </div>
        )}

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search variables..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <div className="text-[10px] text-muted-foreground mt-1 px-1">
            {totalVars} variables available
          </div>
        </div>

        {/* Recently Used */}
        {recentlyUsed.length > 0 && !search && (
          <CollapsibleSection
            variant="subsection"
            title="Recently Used"
            icon={<Clock className="h-3 w-3" />}
            persistKey="template-builder.recently-used"
            defaultCollapsed={false}
          >
            <div className="flex flex-wrap gap-1">
              {recentlyUsed.slice(0, 8).map((varName) => {
                const baseVar = varName.replace(/\.(next|last)$/, "")
                const v = variableMap[baseVar]
                if (!v) return null
                const suffix = varName.includes(".next") ? ".next" : varName.includes(".last") ? ".last" : "base"
                return (
                  <RichTooltip
                    key={varName}
                    side="top"
                    content={
                      <div className="space-y-1.5 text-xs">
                        <div className="text-muted-foreground">{v.description}</div>
                      </div>
                    }
                    disabled={!lastFocusedField}
                  >
                    <button
                      type="button"
                      onClick={() => handleInsert(baseVar, suffix === "base" ? undefined : suffix)}
                      disabled={!lastFocusedField}
                      className="px-2 py-1 text-[11px] font-mono rounded bg-secondary/50 hover:bg-primary/20 text-primary transition-colors disabled:opacity-50"
                    >
                      {`{${varName}}`}
                    </button>
                  </RichTooltip>
                )
              })}
            </div>
          </CollapsibleSection>
        )}

        {/* Categories — controlled CollapsibleSections: single-open accordion,
            with an active search forcing every matching category open. */}
        <div className="space-y-2">
          {filteredCategories.map((cat) => (
            <CollapsibleSection
              key={cat.name}
              variant="subsection"
              title={cat.name}
              count={cat.variables.length}
              collapsed={!(expandedCat === cat.name || !!search)}
              onCollapsedChange={(collapsed) =>
                setExpandedCat(collapsed ? null : cat.name)
              }
            >
              <div className="flex flex-wrap gap-1 pb-1">
                {cat.variables.map((v) => {
                  const suffixClass = isTeamTemplate ? getSuffixClass(v.suffixes) : "var-base"
                  const displayName = !isTeamTemplate || v.suffixes.length <= 1
                    ? v.suffixes.length === 1 && v.suffixes[0] !== "base"
                      ? `${v.name}${v.suffixes[0]}`
                      : v.name
                    : v.name
                  const sample = lookupSample(samples, v)

                  return (
                    <RichTooltip
                      key={v.name}
                      side="top"
                      content={
                        <div className="space-y-1.5 text-xs">
                          <div className="font-mono font-semibold text-primary">{`{${displayName}}`}</div>
                          <div className="text-muted-foreground">{v.description}</div>
                          {sample && (
                            <div className="pt-1 border-t border-border">
                              <span className="text-muted-foreground">e.g. </span>
                              <span className="font-medium">{sample}</span>
                            </div>
                          )}
                        </div>
                      }
                      disabled={!lastFocusedField}
                    >
                      <button
                        type="button"
                        onClick={(e) => handleVariableClick(e, v)}
                        disabled={!lastFocusedField}
                        title={lastFocusedField ? undefined : v.description}
                        className={`
                          px-2 py-1 text-[11px] font-mono rounded border transition-colors
                          disabled:opacity-50 disabled:cursor-not-allowed
                          ${suffixClass === "var-all" ? "bg-blue-500/15 border-blue-500/30 text-blue-400 hover:bg-blue-500/30 hover:text-white hover:border-blue-500" : ""}
                          ${suffixClass === "var-base" ? "bg-gray-500/15 border-gray-500/30 text-gray-400 hover:bg-gray-500/30 hover:text-white hover:border-gray-500" : ""}
                          ${suffixClass === "var-next" ? "bg-green-500/15 border-green-500/30 text-green-400 hover:bg-green-500/30 hover:text-white hover:border-green-500" : ""}
                          ${suffixClass === "var-last" ? "bg-red-500/15 border-red-500/30 text-red-400 hover:bg-red-500/30 hover:text-white hover:border-red-500" : ""}
                        `}
                      >
                        {displayName}
                      </button>
                    </RichTooltip>
                  )
                })}
              </div>
            </CollapsibleSection>
          ))}

          {filteredCategories.length === 0 && (
            <div className="text-center text-sm text-muted-foreground py-4">
              No variables found
            </div>
          )}
        </div>

        {/* Suffix Selector Popup */}
        {suffixPopup && (
          <div
            id="suffix-popup"
            className="fixed z-[100] bg-popover border border-border rounded-lg shadow-xl p-1.5 w-max"
            style={{ left: suffixPopup.x, top: suffixPopup.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="space-y-0.5">
              {suffixPopup.suffixes.map((suffix) => {
                const varText = suffix === "base" ? suffixPopup.varName : `${suffixPopup.varName}${suffix}`
                const desc = suffix === "base" ? "current game" : suffix === ".next" ? "next game" : "last game"
                return (
                  <button
                    key={suffix}
                    type="button"
                    onClick={() => handleInsert(suffixPopup.varName, suffix)}
                    className={`
                      w-full px-2 py-1 text-left rounded transition-colors flex items-center gap-2
                      ${suffix === "base" ? "hover:bg-gray-500/20" : ""}
                      ${suffix === ".next" ? "hover:bg-green-500/20" : ""}
                      ${suffix === ".last" ? "hover:bg-red-500/20" : ""}
                    `}
                  >
                    <code className={`text-xs font-mono font-semibold whitespace-nowrap
                      ${suffix === "base" ? "text-gray-400" : ""}
                      ${suffix === ".next" ? "text-green-400" : ""}
                      ${suffix === ".last" ? "text-red-400" : ""}
                    `}>
                      {`{${varText}}`}
                    </code>
                    <span className="text-[10px] text-muted-foreground whitespace-nowrap">{desc}</span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
