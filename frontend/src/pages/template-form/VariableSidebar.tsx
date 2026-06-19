import { useState, useEffect, useMemo, useRef } from "react"
import { ChevronDown, Search, X, FileText, User, Tv, Clock, Radio } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useTheme } from "@/hooks/useTheme"
import { getLeagueDisplayName, getSportDisplayName } from "@/lib/utils"
import type { CachedLeague } from "@/api/teams"
import type { VariableSidebarProps, Variable } from "./types"

// Compact abbreviation for the preview button: alias if set, else the code.
function leagueAbbrev(l: CachedLeague): string {
  return l.league_alias || l.slug.toUpperCase()
}

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

export function VariableSidebar({ categories, onInsert, lastFocusedField, isTeamTemplate, leagues, subscribedSlugs, previewLeague, onLeagueChange, liveRequested, isLive, onToggleLive, liveCoverage }: VariableSidebarProps) {
  const [search, setSearch] = useState("")
  const [expandedCat, setExpandedCat] = useState<string | null>(null)
  const [recentlyUsed, setRecentlyUsed] = useState<string[]>(() => getRecentlyUsed())
  const [suffixPopup, setSuffixPopup] = useState<{ varName: string; suffixes: string[]; x: number; y: number } | null>(null)
  const [leaguePickerOpen, setLeaguePickerOpen] = useState(false)
  const [leagueSearch, setLeagueSearch] = useState("")
  const leaguePickerRef = useRef<HTMLDivElement>(null)
  const theme = useTheme()

  const selectedLeague = useMemo(
    () => leagues.find((l) => l.slug === previewLeague),
    [leagues, previewLeague],
  )

  const logoFor = (l: CachedLeague): string | null =>
    (theme === "dark" ? l.logo_url_dark : null) || l.logo_url

  // Default view shows the user's subscribed leagues; searching reaches the full
  // list. If the user has no subscriptions yet, the default shows everything.
  const subscribedSet = useMemo(() => new Set(subscribedSlugs), [subscribedSlugs])

  const groupedLeagues = useMemo(() => {
    const q = leagueSearch.trim().toLowerCase()
    const base =
      q || subscribedSet.size === 0
        ? leagues
        : leagues.filter((l) => subscribedSet.has(l.slug))
    const groups: Record<string, CachedLeague[]> = {}
    for (const lg of base) {
      if (
        q &&
        !lg.name.toLowerCase().includes(q) &&
        !lg.sport.toLowerCase().includes(q) &&
        !(lg.league_alias || "").toLowerCase().includes(q)
      )
        continue
      const sport = lg.sport || "Other"
      ;(groups[sport] ||= []).push(lg)
    }
    return Object.entries(groups)
      .map(([sport, items]) => [sport, items.sort((a, b) => a.name.localeCompare(b.name))] as const)
      .sort((a, b) => a[0].localeCompare(b[0]))
  }, [leagues, subscribedSet, leagueSearch])

  // Close the league picker when clicking outside it.
  useEffect(() => {
    if (!leaguePickerOpen) return
    function onDocClick(e: MouseEvent) {
      if (leaguePickerRef.current && !leaguePickerRef.current.contains(e.target as Node)) {
        setLeaguePickerOpen(false)
      }
    }
    document.addEventListener("mousedown", onDocClick)
    return () => document.removeEventListener("mousedown", onDocClick)
  }, [leaguePickerOpen])

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
        {/* Template Type + League Selector */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-2 py-1.5 bg-secondary/50 rounded text-xs">
            <span className="text-muted-foreground">Showing vars for:</span>
            <span className="inline-flex items-center gap-1 font-semibold text-primary">
              {isTeamTemplate ? <User className="h-3 w-3" /> : <Tv className="h-3 w-3" />}
              {isTeamTemplate ? "Team" : "Event"}
            </span>
          </div>
          <div ref={leaguePickerRef} className="relative">
            <div className="flex items-center gap-2 px-2 py-1.5 bg-secondary/50 rounded text-xs">
              <span className="text-muted-foreground shrink-0">Preview:</span>
              <button
                type="button"
                onClick={() => setLeaguePickerOpen((o) => !o)}
                className="flex-1 flex items-center gap-1.5 font-semibold text-primary text-left min-w-0"
                title={selectedLeague?.name ?? previewLeague}
              >
                {selectedLeague && logoFor(selectedLeague) && (
                  <img
                    src={logoFor(selectedLeague)!}
                    alt=""
                    className="h-4 w-4 object-contain shrink-0"
                    onError={(e) => (e.currentTarget.style.display = "none")}
                  />
                )}
                <span className="truncate">
                  {selectedLeague ? leagueAbbrev(selectedLeague) : previewLeague.toUpperCase()}
                </span>
                <ChevronDown className="h-3 w-3 shrink-0 opacity-60 ml-auto" />
              </button>
              <button
                type="button"
                onClick={onToggleLive}
                className={`shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                  isLive
                    ? "bg-green-500/20 text-green-400 hover:bg-green-500/30"
                    : liveRequested
                      ? "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
                      : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
                title={
                  isLive
                    ? "Previewing real provider data — click for sample data"
                    : liveRequested
                      ? "No live event found — showing sample data. Click to return to sample mode"
                      : "Previewing static sample data — click to try live data"
                }
              >
                {isLive && <Radio className="h-2.5 w-2.5" />}
                {isLive ? "Live" : liveRequested ? "No event" : "Sample"}
              </button>
            </div>
            {isLive && liveCoverage && (
              <div className="mt-1 px-2 flex items-center justify-end text-[10px] text-muted-foreground tabular-nums">
                <span
                  title={`${liveCoverage.populated} of ${liveCoverage.total} sport-relevant variables populate from this live event${
                    liveCoverage.gaps.length
                      ? ` — ${liveCoverage.gaps.length} gap${liveCoverage.gaps.length === 1 ? "" : "s"} the event doesn't provide`
                      : ""
                  }`}
                >
                  {liveCoverage.populated}/{liveCoverage.total} variables live
                  {liveCoverage.gaps.length > 0 &&
                    ` · ${liveCoverage.gaps.length} gap${liveCoverage.gaps.length === 1 ? "" : "s"}`}
                </span>
              </div>
            )}
            {leaguePickerOpen && (
              <div className="absolute z-20 mt-1 left-0 right-0 bg-popover border border-border rounded shadow-lg max-h-72 overflow-hidden flex flex-col">
                <div className="p-1.5 border-b border-border">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                    <Input
                      autoFocus
                      value={leagueSearch}
                      onChange={(e) => setLeagueSearch(e.target.value)}
                      placeholder="Search leagues..."
                      className="h-7 pl-7 text-xs"
                    />
                  </div>
                </div>
                {!leagueSearch.trim() && subscribedSet.size > 0 && (
                  <div className="px-2 py-1 text-[10px] text-muted-foreground border-b border-border">
                    Your subscribed leagues — search to find any league
                  </div>
                )}
                <div className="overflow-y-auto text-xs">
                  {groupedLeagues.length === 0 && (
                    <div className="px-2 py-3 text-center text-muted-foreground">No leagues found</div>
                  )}
                  {groupedLeagues.map(([sport, items]) => (
                    <div key={sport}>
                      <div className="px-2 py-1 sticky top-0 bg-secondary/80 text-[10px] uppercase tracking-wide text-muted-foreground font-semibold">
                        {getSportDisplayName(sport)}
                      </div>
                      {items.map((lg) => (
                        <button
                          key={lg.slug}
                          type="button"
                          onClick={() => {
                            onLeagueChange(lg.slug)
                            setLeaguePickerOpen(false)
                            setLeagueSearch("")
                          }}
                          className={`w-full text-left px-3 py-1.5 hover:bg-accent flex items-center gap-2 ${
                            lg.slug === previewLeague ? "text-primary font-semibold" : ""
                          }`}
                        >
                          {logoFor(lg) ? (
                            <img
                              src={logoFor(lg)!}
                              alt=""
                              className="h-4 w-4 object-contain shrink-0"
                              onError={(e) => (e.currentTarget.style.display = "none")}
                            />
                          ) : (
                            <span className="h-4 w-4 shrink-0" />
                          )}
                          <span className="truncate">{getLeagueDisplayName(lg)}</span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

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
          <details className="group" open>
            <summary className="cursor-pointer text-xs font-medium text-foreground hover:text-primary flex items-center gap-1">
              <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
              <Clock className="h-3 w-3" /> Recently Used
            </summary>
            <div className="flex flex-wrap gap-1 mt-2">
              {recentlyUsed.slice(0, 8).map((varName) => {
                const baseVar = varName.replace(/\.(next|last)$/, "")
                const v = variableMap[baseVar]
                if (!v) return null
                const suffix = varName.includes(".next") ? ".next" : varName.includes(".last") ? ".last" : "base"
                return (
                  <button
                    key={varName}
                    type="button"
                    onClick={() => handleInsert(baseVar, suffix === "base" ? undefined : suffix)}
                    disabled={!lastFocusedField}
                    className="px-2 py-1 text-[11px] font-mono rounded bg-secondary/50 hover:bg-primary/20 text-primary transition-colors disabled:opacity-50"
                  >
                    {`{${varName}}`}
                  </button>
                )
              })}
            </div>
          </details>
        )}

        {/* Categories */}
        <div className="space-y-1">
          {filteredCategories.map((cat) => (
            <details
              key={cat.name}
              className="group border-b border-border last:border-0"
              open={expandedCat === cat.name || !!search}
            >
              <summary
                onClick={(e) => {
                  e.preventDefault()
                  setExpandedCat(expandedCat === cat.name ? null : cat.name)
                }}
                className="cursor-pointer px-1 py-1.5 flex items-center justify-between text-xs font-medium hover:bg-accent/50 transition-colors"
              >
                <span>{cat.name}</span>
                <span className="text-[10px] text-muted-foreground">{cat.variables.length}</span>
              </summary>
              <div className="flex flex-wrap gap-1 pb-2 pt-1">
                {cat.variables.map((v) => {
                  const suffixClass = isTeamTemplate ? getSuffixClass(v.suffixes) : "var-base"
                  const displayName = !isTeamTemplate || v.suffixes.length <= 1
                    ? v.suffixes.length === 1 && v.suffixes[0] !== "base"
                      ? `${v.name}${v.suffixes[0]}`
                      : v.name
                    : v.name

                  return (
                    <button
                      key={v.name}
                      type="button"
                      onClick={(e) => handleVariableClick(e, v)}
                      disabled={!lastFocusedField}
                      title={v.description}
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
                  )
                })}
              </div>
            </details>
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
                      ${suffix === "base" ? "hover:bg-emerald-500/20" : ""}
                      ${suffix === ".next" ? "hover:bg-blue-500/20" : ""}
                      ${suffix === ".last" ? "hover:bg-amber-500/20" : ""}
                    `}
                  >
                    <code className={`text-xs font-mono font-semibold whitespace-nowrap
                      ${suffix === "base" ? "text-emerald-400" : ""}
                      ${suffix === ".next" ? "text-blue-400" : ""}
                      ${suffix === ".last" ? "text-amber-400" : ""}
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
