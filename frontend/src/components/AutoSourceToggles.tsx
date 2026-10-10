import { useMemo, useState } from "react"
import { Link } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { AlertTriangle, Sparkles } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useSchedulerSettings, useUpdateSchedulerSettings } from "@/hooks/useSettings"
import { useSubscription, useUpdateSubscription } from "@/hooks/useSubscription"
import { useSports } from "@/hooks/useSports"
import { getLeagues } from "@/api/teams"
import { getLeagueDisplayName, getSportDisplayName } from "@/lib/utils"

/**
 * "Find sources automatically" toggles (#997), per subscribed league and per
 * sport. With a toggle on, the daily source-discovery scan adds M3U groups
 * carrying that league's events as managed sources on its own instead of
 * only suggesting them. A sport toggle covers every league under it, including
 * ones discovered later. Saved immediately; independent of the picker's Save.
 *
 * The toggles only act when the daily scan runs, so the card says when that is
 * and warns, with a link to the switch, while the scan is off (#1027). The
 * auto-add stream cap lives here too: it only ever gates automatic adding.
 */
export function AutoSourceToggles() {
  const { data: subscription } = useSubscription()
  const update = useUpdateSubscription()
  const { data: leaguesResponse } = useQuery({ queryKey: ["leagues"], queryFn: () => getLeagues() })
  const sportsMap = useSports().data?.sports
  const { data: scheduler } = useSchedulerSettings()
  const updateScheduler = useUpdateSchedulerSettings()
  const scanOff = scheduler?.source_discovery_mode === "off"

  // The cap is edited locally and saved on blur / Enter, so a half-typed number
  // never reaches the server.
  const [capDraft, setCapDraft] = useState<string | null>(null)
  const cap = capDraft ?? String(scheduler?.source_discovery_auto_max_streams ?? 1000)
  const saveCap = () => {
    const n = Number.parseInt(cap, 10)
    setCapDraft(null)
    if (!Number.isFinite(n) || n < 1 || n === scheduler?.source_discovery_auto_max_streams) return
    updateScheduler.mutate(
      { source_discovery_auto_max_streams: n },
      { onError: (e) => toast.error(e instanceof Error ? e.message : "Failed to save") },
    )
  }

  const autoLeagues = useMemo(
    () => new Set((subscription?.auto_source_leagues ?? []).map((s) => s.toLowerCase())),
    [subscription],
  )
  const autoSports = useMemo(
    () => new Set((subscription?.auto_source_sports ?? []).map((s) => s.toLowerCase())),
    [subscription],
  )

  // Subscribed leagues grouped by sport. Soccer in "all leagues" mode has no
  // per-league list, so it is offered as a sport only.
  const groups = useMemo(() => {
    const subscribed = new Set((subscription?.leagues ?? []).map((s) => s.toLowerCase()))
    const bySport = new Map<string, { slug: string; label: string }[]>()
    for (const lg of leaguesResponse?.leagues ?? []) {
      const sport = (lg.sport || "other").toLowerCase()
      if (!subscribed.has(lg.slug.toLowerCase())) continue
      const list = bySport.get(sport) ?? []
      list.push({ slug: lg.slug.toLowerCase(), label: getLeagueDisplayName(lg, true) })
      bySport.set(sport, list)
    }
    if (subscription?.soccer_mode === "all" && !bySport.has("soccer")) bySport.set("soccer", [])
    return [...bySport.entries()]
      .map(([sport, list]) => [sport, list.sort((a, b) => a.label.localeCompare(b.label))] as const)
      .sort((a, b) => a[0].localeCompare(b[0]))
  }, [subscription, leaguesResponse])

  const save = (leagues: Set<string>, sports: Set<string>) =>
    update.mutate(
      { auto_source_leagues: [...leagues], auto_source_sports: [...sports] },
      { onError: (e) => toast.error(e instanceof Error ? e.message : "Failed to save") },
    )

  const toggleLeague = (slug: string) => {
    const next = new Set(autoLeagues)
    if (next.has(slug)) next.delete(slug)
    else next.add(slug)
    save(next, autoSports)
  }
  const toggleSport = (sport: string) => {
    const next = new Set(autoSports)
    if (next.has(sport)) next.delete(sport)
    else next.add(sport)
    save(autoLeagues, next)
  }

  if (!subscription || groups.length === 0) return null

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4" />
        <Label className="text-base font-medium">Find sources automatically</Label>
      </div>
      <p className="text-xs text-muted-foreground">
        Source discovery scans your M3U groups once a day; to check sooner, press Scan now under{" "}
        <Link to="/sources" className="underline underline-offset-2">
          Sources → Suggested sources
        </Link>
        . For a league or sport switched on here, groups carrying its events are added as sources
        on their own instead of waiting in the Suggested sources list. A sport covers every league
        under it. Groups you dismissed, replay groups and linear channels with guide data (EPG
        matching) are never added.
      </p>
      {scanOff && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-400"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            The daily scan is switched off, so these switches do nothing. Turn on{" "}
            <Link to="/sources" className="font-medium underline underline-offset-2">
              Scan daily
            </Link>{" "}
            under Sources → Suggested sources, or press Scan now there.
          </span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Label
          htmlFor="discovery-cap"
          className="text-xs"
          title="A group with more streams than this is suggested, never added automatically."
        >
          Auto-add groups up to (streams)
        </Label>
        <Input
          id="discovery-cap"
          type="number"
          min={1}
          value={cap}
          onChange={(e) => setCapDraft(e.target.value)}
          onBlur={saveCap}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur()
          }}
          className="h-8 w-28"
        />
      </div>
      <div className="space-y-3">
        {groups.map(([sport, leagues]) => {
          const sportOn = autoSports.has(sport)
          return (
            <div key={sport} className="rounded-lg border border-border">
              <div className="flex items-center justify-between px-3 py-2 bg-muted/40">
                <span className="text-sm font-semibold">{getSportDisplayName(sport, sportsMap)}</span>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  all {getSportDisplayName(sport, sportsMap)} leagues
                  <Switch checked={sportOn} onCheckedChange={() => toggleSport(sport)} />
                </label>
              </div>
              {leagues.length > 0 && (
                <div className="divide-y divide-border">
                  {leagues.map((lg) => (
                    <div key={lg.slug} className="flex items-center justify-between px-3 py-1.5 text-sm">
                      <span className={sportOn ? "text-muted-foreground" : ""}>{lg.label}</span>
                      <Switch
                        checked={sportOn || autoLeagues.has(lg.slug)}
                        disabled={sportOn}
                        onCheckedChange={() => toggleLeague(lg.slug)}
                        aria-label={`Find sources automatically for ${lg.label}`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}
