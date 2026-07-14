import { useState, useEffect, useMemo, useRef } from "react"
import { ChevronDown, Search, Radio, Eye } from "lucide-react"
import { Input } from "@/components/ui/input"
import { useTheme } from "@/hooks/useTheme"
import { getLeagueDisplayName, getSportDisplayName } from "@/lib/utils"
import type { CachedLeague } from "@/api/teams"
import type { PreviewControlsProps } from "./types"

// Compact abbreviation for the preview button: alias if set, else the code.
function leagueAbbrev(l: CachedLeague): string {
  return l.league_alias || l.slug.toUpperCase()
}

/**
 * Slim preview-context bar above the builder tabs (yk4j.10): the league picker
 * and Live/Sample toggle that drive EVERY preview on the page — the guide card,
 * the inline per-field previews, and the condition trace. Moved here from the
 * variable sidebar so the preview context reads as page-level state, not a
 * sidebar detail.
 */
export function PreviewControls({
  leagues,
  subscribedSlugs,
  previewLeague,
  onLeagueChange,
  liveRequested,
  isLive,
  onToggleLive,
  liveCoverage,
}: PreviewControlsProps) {
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

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-1.5 rounded-lg bg-secondary/40 border border-border text-xs">
      <span className="inline-flex items-center gap-1.5 text-muted-foreground shrink-0">
        <Eye className="h-3.5 w-3.5" />
        Previewing as:
      </span>
      <div ref={leaguePickerRef} className="relative">
        <button
          type="button"
          onClick={() => setLeaguePickerOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-border bg-background/60 font-semibold text-primary hover:bg-accent transition-colors min-w-0"
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
          <span className="truncate max-w-32">
            {selectedLeague ? leagueAbbrev(selectedLeague) : previewLeague.toUpperCase()}
          </span>
          <ChevronDown className="h-3 w-3 shrink-0 opacity-60" />
        </button>
        {leaguePickerOpen && (
          <div className="absolute z-20 mt-1 left-0 w-72 bg-popover border border-border rounded shadow-lg max-h-72 overflow-hidden flex flex-col">
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
      <button
        type="button"
        onClick={onToggleLive}
        className={`shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold transition-colors ${
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
      {isLive && liveCoverage && (
        <span
          className="ml-auto text-[10px] text-muted-foreground tabular-nums"
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
      )}
    </div>
  )
}
