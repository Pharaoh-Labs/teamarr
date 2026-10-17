import { useMemo, useState, type InputHTMLAttributes } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { LoaderCircle, Pin, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioCards } from "@/components/ui/radio-cards"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { TeamPicker } from "@/components/TeamPicker"
import { getLeagues, getTeamPickerLeagues } from "@/api/teams"
import { useRaceFeeds } from "@/hooks/useRaceFeeds"
import type { RaceFeed } from "@/api/raceFeeds"
import { useSports } from "@/hooks/useSports"
import { getSportDisplayName } from "@/lib/utils"
import {
  useCreateNumberingException,
  useDeleteNumberingException,
  useNumberingExceptions,
  useNumberingPreview,
  useSegmentCodes,
  useUpdateNumberingException,
} from "@/hooks/useNumberingExceptions"
import type { NumberingException, NumberingScope } from "@/api/numberingExceptions"
import type { TeamFilterEntry } from "@/api/types"

/**
 * Channels → Numbering → Pinned Blocks (#333).
 *
 * A block pins a team / league / sport to a fixed channel start. A start belongs
 * to one block; rows may share a start only under the same group name (the
 * server rejects any other collision). Most specific wins (team › league ›
 * sport). Everything unmatched numbers from the global range. Edits arm a
 * re-grid in sticky modes, so the change lands on the next generation.
 *
 * A block may be limited to one season type and may name the channel group its
 * channels go to (#950) — "NBA postseason at 900, in 09 TEAMARR {league}". It may
 * also be limited to session / card-segment codes and to one kind of channel
 * (main, driver feeds, other race feeds, one feed) — "F1 race and qualifying at
 * 1200" (#1018). Those controls sit under Advanced.
 */

const SEASON_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Any season" },
  { value: "preseason", label: "Preseason" },
  { value: "regular", label: "Regular season" },
  { value: "postseason", label: "Postseason" },
]

const KEYWORD_PRESETS: { value: string; label: string }[] = [
  { value: "", label: "Any channel" },
  { value: "main", label: "Main channel only" },
  { value: "any", label: "Any keyword channel" },
]

// Race-feed kinds, offered only where the league (or racing sport) has race feeds.
const KEYWORD_RACE_KINDS: { value: string; label: string }[] = [
  { value: "driver", label: "Any driver feed" },
  { value: "variant", label: "Any other race feed" },
]

// Select value that reveals the keyword-label input. A stored label keyword is
// "label:<label>"; the bare prefix means "keyword chosen, label not typed yet".
const LABEL_PREFIX = "label:"

const parseSegments = (raw: string): string[] | null => {
  const codes = Array.from(
    new Set(
      raw
        .split(",")
        .map((c) => c.trim().toLowerCase())
        .filter(Boolean)
    )
  )
  return codes.length ? codes : null
}

/** A keyword value that still needs its label typed. */
const isIncompleteKeyword = (v: string) =>
  v.startsWith(LABEL_PREFIX) && !v.slice(LABEL_PREFIX.length).trim()

/** Race-feed options for a block: feeds of its league, or none for a racing sport. */
type RaceOptions = { feeds: RaceFeed[] } | null

const keywordLabel = (keyword: string, feeds: RaceFeed[]): string => {
  const preset = [...KEYWORD_PRESETS, ...KEYWORD_RACE_KINDS].find((o) => o.value === keyword)
  if (preset) return preset.label
  if (keyword.startsWith("feed:")) {
    const row = feeds.find((f) => f.feed_key === keyword.slice(5))
    return row ? row.label : keyword.slice(5)
  }
  if (keyword.startsWith(LABEL_PREFIX)) return `Keyword ${keyword.slice(LABEL_PREFIX.length)}`
  return keyword
}

/**
 * Keyword condition select. Its mode comes from ``value`` alone: the label
 * input shows while the value starts with "label:". ``onChange`` fires on every
 * edit; ``onCommit`` (optional) fires when a choice is final, meaning a select
 * pick or the label input losing focus.
 */
function KeywordSelect({
  value,
  onChange,
  onCommit,
  race,
  id,
  className,
}: {
  value: string
  onChange: (v: string) => void
  onCommit?: (v: string) => void
  race: RaceOptions
  id?: string
  className?: string
}) {
  const labelMode = value.startsWith(LABEL_PREFIX)
  const feeds = race?.feeds ?? []
  const known =
    labelMode ||
    KEYWORD_PRESETS.some((o) => o.value === value) ||
    (race !== null && KEYWORD_RACE_KINDS.some((o) => o.value === value)) ||
    feeds.some((f) => `feed:${f.feed_key}` === value)
  const pick = (v: string) => {
    onChange(v)
    onCommit?.(v)
  }
  return (
    <>
      <Select
        id={id}
        value={labelMode ? LABEL_PREFIX : value}
        onChange={(e) => pick(e.target.value)}
        className={className}
        aria-label="Keyword"
      >
        {KEYWORD_PRESETS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        {race &&
          KEYWORD_RACE_KINDS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        {feeds.map((f) => (
          <option key={f.feed_key} value={`feed:${f.feed_key}`}>
            {f.label}
          </option>
        ))}
        <option value={LABEL_PREFIX}>Specific keyword…</option>
        {!known && <option value={value}>{keywordLabel(value, feeds)}</option>}
      </Select>
      {labelMode && (
        <Input
          value={value.slice(LABEL_PREFIX.length)}
          onChange={(e) => onChange(`${LABEL_PREFIX}${e.target.value}`)}
          onBlur={() => onCommit?.(value)}
          className="w-36 h-8"
          placeholder="Keyword label"
          aria-label="Keyword label"
        />
      )}
    </>
  )
}

/** Segments text input with a datalist of the known codes for the block's sport. */
function SegmentsInput({
  codes,
  listId,
  ...props
}: {
  codes: string[]
  listId: string
} & Omit<InputHTMLAttributes<HTMLInputElement>, "list">) {
  return (
    <>
      <Input list={listId} {...props} />
      <datalist id={listId}>
        {codes.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
    </>
  )
}

/** Race-feed options a block can offer, given the leagues the race-feeds API lists. */
function raceOptionsFor(
  leagueCode: string | null | undefined,
  sport: string | null | undefined,
  scope: NumberingScope,
  raceLeagues: string[],
  feeds: RaceFeed[]
): RaceOptions {
  if (leagueCode && raceLeagues.includes(leagueCode)) {
    return { feeds: feeds.filter((f) => f.league === leagueCode) }
  }
  if (scope === "sport" && sport === "racing") return { feeds: [] }
  return null
}

/** Segments and keyword of a block as summary-row text. */
function BlockConditions({ b, feeds }: { b: NumberingException; feeds: RaceFeed[] }) {
  return (
    <>
      {b.segments && ` · segments: ${b.segments.join(", ")}`}
      {b.keyword && ` · keyword: ${keywordLabel(b.keyword, feeds)}`}
    </>
  )
}

/** One row's keyword select. A half-typed label stays a draft until it is complete. */
function BlockKeyword({
  b,
  race,
  onSave,
}: {
  b: NumberingException
  race: RaceOptions
  onSave: (b: NumberingException, value: string) => Promise<void>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const commit = async (v: string) => {
    if (isIncompleteKeyword(v)) return
    const next = v.startsWith(LABEL_PREFIX) ? `${LABEL_PREFIX}${v.slice(6).trim()}` : v
    try {
      if (next !== (b.keyword ?? "")) await onSave(b, next)
    } finally {
      setDraft(null)
    }
  }
  return (
    <KeywordSelect
      value={draft ?? b.keyword ?? ""}
      onChange={setDraft}
      onCommit={commit}
      race={race}
      className="w-44 h-8"
    />
  )
}

const SCOPE_LABEL: Record<NumberingScope, string> = {
  team: "Team",
  league: "League",
  sport: "Sport",
}

const SCOPE_VARIANT: Record<NumberingScope, "default" | "secondary" | "outline"> = {
  team: "default",
  league: "secondary",
  sport: "outline",
}

export function PinnedBlocks({ rangeStart }: { rangeStart: number }) {
  const { data: blocks, isLoading } = useNumberingExceptions()
  const { data: preview } = useNumberingPreview()
  const remove = useDeleteNumberingException()
  const update = useUpdateNumberingException()
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports

  const { data: raceData } = useRaceFeeds()
  const { data: segmentCodes } = useSegmentCodes()
  const raceLeagues = useMemo(() => raceData?.leagues ?? [], [raceData])
  const raceFeeds = useMemo(() => raceData?.feeds ?? [], [raceData])

  const [addOpen, setAddOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggleExpanded = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const sorted = useMemo(() => blocks ?? [], [blocks])

  const onDelete = async (b: NumberingException) => {
    try {
      await remove.mutateAsync(b.id)
      toast.success(`Removed ${b.display_name ?? "block"}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove block")
    }
  }

  const onToggle = async (b: NumberingException, enabled: boolean) => {
    try {
      await update.mutateAsync({ id: b.id, data: { enabled } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update block")
    }
  }

  const onStartBlur = async (b: NumberingException, raw: string) => {
    const v = parseInt(raw)
    if (isNaN(v) || v < 1 || v === b.start) return
    try {
      await update.mutateAsync({ id: b.id, data: { start: v } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update start")
    }
  }

  const onSeasonChange = async (b: NumberingException, value: string) => {
    try {
      await update.mutateAsync({
        id: b.id,
        data: { season_type: value || null, set_season_type: true },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update season")
    }
  }

  const onSegmentsBlur = async (b: NumberingException, raw: string) => {
    const next = parseSegments(raw)
    if ((next ?? []).join(",") === (b.segments ?? []).join(",")) return
    try {
      await update.mutateAsync({ id: b.id, data: { segments: next, set_segments: true } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update segments")
    }
  }

  const onKeywordChange = async (b: NumberingException, value: string) => {
    try {
      await update.mutateAsync({ id: b.id, data: { keyword: value || null, set_keyword: true } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update keyword")
    }
  }

  const onGroupBlur = async (b: NumberingException, raw: string) => {
    const v = raw.trim()
    if (v === (b.channel_group_mode ?? "")) return
    try {
      await update.mutateAsync({
        id: b.id,
        data: {
          channel_group_mode: v || null,
          channel_group_id: v ? b.channel_group_id : null,
          set_channel_group: true,
        },
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update channel group")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Pin className="h-4 w-4" /> Pinned Blocks
            </CardTitle>
            <CardDescription>
              Give a team, league, or sport its own block of channel numbers, starting
              anywhere — above, below, or inside the Everything Else range ({rangeStart}+),
              which flows around it. Most specific wins: Team › League › Sport. Each start
              belongs to one block — to put a team first inside its league&apos;s block, use
              Priority Teams above. Blocks spill forward if they fill up. A block can be
              limited to one season (playoffs only, say) and can send its channels to its
              own channel group. Under Advanced, racing and MMA blocks can also be limited
              to sessions (race, qualifying…) and to the main channel or a kind of keyword.
            </CardDescription>
          </div>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> Add block
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <LoaderCircle className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">
            No pinned blocks. All channels number from {rangeStart} in lineup order.
          </p>
        ) : (
          <div className="border rounded-md divide-y">
            {sorted.map((b) => (
              <div
                key={b.id}
                className={`flex flex-wrap items-center gap-3 px-3 py-2 ${b.enabled ? "" : "opacity-60"}`}
              >
                <Input
                  type="number"
                  min={1}
                  defaultValue={b.start}
                  key={`start-${b.id}-${b.start}`}
                  className="w-24 h-8 text-right font-mono"
                  onBlur={(e) => onStartBlur(b, e.target.value)}
                  aria-label="Block start"
                />
                <Badge variant={SCOPE_VARIANT[b.scope]} className="w-16 justify-center">
                  {SCOPE_LABEL[b.scope]}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">
                    {b.display_name ?? b.team_name ?? b.league_code ?? b.sport}
                    {b.label && (
                      <span className="ml-2 text-xs text-muted-foreground">· {b.label}</span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {getSportDisplayName(b.sport, sportsMap)}
                    {b.end != null && ` · ends at ${b.end}`}
                    <BlockConditions b={b} feeds={raceFeeds} />
                    {` · ${b.channel_count} channel${b.channel_count === 1 ? "" : "s"} today`}
                  </div>
                </div>
                <Select
                  value={b.season_type ?? ""}
                  onChange={(e) => onSeasonChange(b, e.target.value)}
                  className="w-36 h-8"
                  aria-label="Season"
                >
                  {SEASON_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
                {(() => {
                  const codes = segmentCodes?.[b.sport] ?? []
                  const race = raceOptionsFor(
                    b.league_code,
                    b.sport,
                    b.scope,
                    raceLeagues,
                    raceFeeds
                  )
                  const open = expanded.has(b.id) || !!b.segments || !!b.keyword
                  if (!open) return null
                  return (
                    <>
                      {codes.length > 0 && (
                        <SegmentsInput
                          codes={codes}
                          listId={`segments-codes-${b.id}`}
                          defaultValue={(b.segments ?? []).join(", ")}
                          key={`segments-${b.id}-${(b.segments ?? []).join(",")}`}
                          className="w-36 h-8"
                          placeholder="Any segment"
                          onBlur={(e) => onSegmentsBlur(b, e.target.value)}
                          aria-label="Segments"
                        />
                      )}
                      <BlockKeyword b={b} race={race} onSave={onKeywordChange} />
                    </>
                  )
                })()}
                <button
                  type="button"
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  onClick={() => toggleExpanded(b.id)}
                  aria-expanded={expanded.has(b.id)}
                >
                  Advanced
                </button>
                <Input
                  defaultValue={b.channel_group_mode ?? ""}
                  key={`group-${b.id}-${b.channel_group_mode ?? ""}`}
                  className="w-48 h-8"
                  placeholder="Channel group pattern"
                  onBlur={(e) => onGroupBlur(b, e.target.value)}
                  aria-label="Channel group pattern"
                />
                <Switch
                  checked={b.enabled}
                  onCheckedChange={(v) => onToggle(b, v)}
                  aria-label="Enabled"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => onDelete(b)}
                  disabled={remove.isPending}
                  aria-label="Remove block"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {preview && preview.length > 1 && (
          <div className="rounded-md bg-muted/40 px-3 py-2">
            <div className="text-xs font-medium text-muted-foreground mb-1">
              Effective layout (today&apos;s channels, compact placement)
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-mono">
              {preview.map((lane) => (
                <span
                  key={lane.id ?? "default"}
                  className={lane.spills_into_next ? "text-amber-600 dark:text-amber-400" : ""}
                  title={lane.spills_into_next ? "This block spills into the next one" : undefined}
                >
                  {lane.channel_count > 0
                    ? `${lane.first_number}–${lane.last_number}`
                    : `${lane.start}+`}{" "}
                  <span className="font-sans text-muted-foreground">
                    {lane.label} ({lane.channel_count})
                    {lane.spills_into_next ? " ⚠" : ""}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>

      <AddBlockDialog open={addOpen} onOpenChange={setAddOpen} existing={sorted} />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Add dialog
// ---------------------------------------------------------------------------

function AddBlockDialog({
  open,
  onOpenChange,
  existing,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  existing: NumberingException[]
}) {
  const create = useCreateNumberingException()
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports

  const { data: leagueData } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(),
    enabled: open,
  })
  const { data: pickerLeagues } = useQuery({
    queryKey: ["team-picker-leagues"],
    queryFn: getTeamPickerLeagues,
    staleTime: 5 * 60 * 1000,
    enabled: open,
  })
  const pickerSlugs = useMemo(
    () => (pickerLeagues?.leagues ?? []).filter((l) => l.team_count > 0).map((l) => l.slug),
    [pickerLeagues]
  )
  const leagues = useMemo(
    () =>
      [...(leagueData?.leagues ?? [])].sort(
        (a, b) =>
          (a.sport ?? "").localeCompare(b.sport ?? "") || (a.name ?? "").localeCompare(b.name ?? "")
      ),
    [leagueData]
  )
  const sports = useMemo(
    () => Object.entries(sportsMap ?? {}).sort((a, b) => a[1].localeCompare(b[1])),
    [sportsMap]
  )
  const { data: raceData } = useRaceFeeds()
  const { data: segmentCodes } = useSegmentCodes()
  const raceLeagues = useMemo(() => raceData?.leagues ?? [], [raceData])
  const raceFeeds = useMemo(() => raceData?.feeds ?? [], [raceData])
  const groupLabels = useMemo(
    () => Array.from(new Set(existing.map((b) => b.label).filter(Boolean) as string[])),
    [existing]
  )

  const [scope, setScope] = useState<NumberingScope>("team")
  const [team, setTeam] = useState<TeamFilterEntry[]>([])
  const [leagueCode, setLeagueCode] = useState("")
  const [sport, setSport] = useState("")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [label, setLabel] = useState("")
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [season, setSeason] = useState("")
  const [segments, setSegments] = useState("")
  const [keyword, setKeyword] = useState("")
  const [groupPattern, setGroupPattern] = useState("")

  const reset = () => {
    setScope("team")
    setTeam([])
    setLeagueCode("")
    setSport("")
    setStart("")
    setEnd("")
    setLabel("")
    setShowAdvanced(false)
    setSeason("")
    setSegments("")
    setKeyword("")
    setGroupPattern("")
  }

  // Joining an existing group pre-fills its start.
  const onLabelChange = (v: string) => {
    setLabel(v)
    const match = existing.find((b) => b.label === v)
    if (match && !start) setStart(String(match.start))
  }

  // Sport of the chosen scope, for the segment codes and race-feed options.
  const scopeLeague =
    scope === "league" ? leagueCode : scope === "team" ? (team[0]?.league ?? "") : ""
  const scopeSport =
    scope === "sport" ? sport : (leagues.find((l) => l.slug === scopeLeague)?.sport ?? "")
  const codes = segmentCodes?.[scopeSport] ?? []
  const race = raceOptionsFor(scopeLeague, scopeSport, scope, raceLeagues, raceFeeds)

  // Race-feed choices made for an earlier scope do not carry to one without feeds.
  const raceOnly =
    keyword === "driver" || keyword === "variant" || keyword.startsWith("feed:")
  const submitKeyword = keyword.startsWith(LABEL_PREFIX)
    ? `${LABEL_PREFIX}${keyword.slice(LABEL_PREFIX.length).trim()}`
    : raceOnly && race === null
      ? null
      : keyword || null

  const startNum = parseInt(start)
  const endNum = end === "" ? null : parseInt(end)
  const valid =
    !isNaN(startNum) &&
    startNum >= 1 &&
    (endNum === null || (!isNaN(endNum) && endNum >= startNum)) &&
    (scope === "team" ? team.length === 1 : scope === "league" ? !!leagueCode : !!sport) &&
    !isIncompleteKeyword(keyword)

  const submit = async () => {
    if (!valid) return
    try {
      await create.mutateAsync({
        scope,
        start: startNum,
        end: endNum,
        label: label.trim() || null,
        sport: scope === "sport" ? sport : null,
        league_code: scope === "league" ? leagueCode : null,
        provider: scope === "team" ? team[0].provider : null,
        team_id: scope === "team" ? team[0].team_id : null,
        team_league: scope === "team" ? team[0].league : null,
        season_type: season || null,
        segments: codes.length > 0 ? parseSegments(segments) : null,
        keyword: submitKeyword,
        channel_group_mode: groupPattern.trim() || null,
      })
      toast.success("Block added — re-grid queued for the next generation")
      reset()
      onOpenChange(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add block")
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) reset()
        onOpenChange(v)
      }}
    >
      <DialogContent className="max-w-lg" onClose={() => onOpenChange(false)}>
        <DialogHeader>
          <DialogTitle>Add pinned block</DialogTitle>
          <DialogDescription>
            Channels matching this scope number from the block start instead of
            Everything Else. The start can be anywhere.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <RadioCards
            name="pin-scope"
            value={scope}
            onChange={(v) => setScope(v as NumberingScope)}
            options={[
              { value: "team", label: "Team", description: "Its team channel and every game it plays" },
              { value: "league", label: "League", description: "Every channel in the league" },
              { value: "sport", label: "Sport", description: "Every league in the sport" },
            ]}
          />

          {scope === "team" && (
            <div className="space-y-2">
              <Label>Team</Label>
              <TeamPicker
                leagues={pickerSlugs}
                selectedTeams={team}
                onSelectionChange={(t) => setTeam(t.slice(-1))}
                placeholder="Pick a team…"
                singleSelect
              />
            </div>
          )}
          {scope === "league" && (
            <div className="space-y-2">
              <Label htmlFor="pin-league">League</Label>
              <Select
                id="pin-league"
                value={leagueCode}
                onChange={(e) => setLeagueCode(e.target.value)}
              >
                <option value="">Select a league…</option>
                {leagues.map((l) => (
                  <option key={l.slug} value={l.slug}>
                    {getSportDisplayName(l.sport, sportsMap)} — {l.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
          {scope === "sport" && (
            <div className="space-y-2">
              <Label htmlFor="pin-sport">Sport</Label>
              <Select id="pin-sport" value={sport} onChange={(e) => setSport(e.target.value)}>
                <option value="">Select a sport…</option>
                {sports.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </Select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="pin-start">Start channel</Label>
              <Input
                id="pin-start"
                type="number"
                min={1}
                value={start}
                onChange={(e) => setStart(e.target.value)}
                placeholder="e.g. 800"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pin-label">Group (optional)</Label>
              <Input
                id="pin-label"
                list="pin-group-labels"
                value={label}
                onChange={(e) => onLabelChange(e.target.value)}
                placeholder="e.g. Big events"
              />
              <datalist id="pin-group-labels">
                {groupLabels.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
            </div>
          </div>
          <p className="text-xs text-muted-foreground -mt-2">
            Each start belongs to one block. To share a block between several teams, leagues,
            or sports, give them the same group name and start.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="pin-season">Season</Label>
              <Select id="pin-season" value={season} onChange={(e) => setSeason(e.target.value)}>
                {SEASON_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pin-group-pattern">Channel group (optional)</Label>
              <Input
                id="pin-group-pattern"
                value={groupPattern}
                onChange={(e) => setGroupPattern(e.target.value)}
                placeholder="e.g. 09 TEAMARR {league}"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground -mt-2">
            A season limits the block to those games; the rest number as if the block were
            not there. A channel group pattern (with {"{sport}"} or {"{league}"}) overrides the
            group these channels would otherwise use.
          </p>

          {showAdvanced ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {codes.length > 0 && (
                  <div className="space-y-2">
                    <Label htmlFor="pin-segments">Segments (optional)</Label>
                    <SegmentsInput
                      id="pin-segments"
                      codes={codes}
                      listId="pin-segment-codes"
                      value={segments}
                      onChange={(e) => setSegments(e.target.value)}
                      placeholder={codes.slice(-2).join(", ")}
                    />
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="pin-keyword">Keyword</Label>
                  <KeywordSelect
                    id="pin-keyword"
                    value={keyword}
                    onChange={setKeyword}
                    race={race}
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground -mt-2">
                {codes.length > 0 &&
                  `Segments are comma-separated codes (${codes.join(", ")}); the block then holds only those. `}
                Keyword limits the block to the main channel, any keyword channel, or one
                keyword. Among blocks of the same scope, the most specific keyword wins, then
                segments, then season.
              </p>

              <div className="space-y-2 max-w-[50%]">
                <Label htmlFor="pin-end">End channel</Label>
                <Input
                  id="pin-end"
                  type="number"
                  min={1}
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  placeholder="No limit"
                />
                <p className="text-xs text-muted-foreground">
                  When the block is full, extra channels overflow to Everything Else instead
                  of spilling forward.
                </p>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="text-xs text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => setShowAdvanced(true)}
            >
              Advanced: segments, keyword, end channel
            </button>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!valid || create.isPending}>
            {create.isPending ? "Adding…" : "Add block"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
