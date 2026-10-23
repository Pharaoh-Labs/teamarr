import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CalendarPlus, Pencil, TriangleAlert, X } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Alert } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  type ManualEvent,
  type ManualEventInput,
} from "@/api/manualEvents"
import {
  useCancelManualEvent,
  useCreateManualEvent,
  useManualEventDuplicates,
  useManualEvents,
  useUpdateManualEvent,
} from "@/hooks/useManualEvents"
import { getLeagueTeams, getTeamPickerLeagues, type CachedTeam } from "@/api/teams"
import { api } from "@/api/client"

interface EventSearchHit {
  event_id: string
  event_name: string
  start_time: string
  home_team: string | null
  away_team: string | null
}

interface FormState {
  league: string
  homeId: string
  awayId: string
  /** datetime-local value; interpreted in the browser's timezone on submit. */
  kickoff: string
  name: string
  venue: string
  seasonType: "preseason" | "regular" | "postseason"
  neutralSite: boolean
}

const EMPTY_FORM: FormState = {
  league: "",
  homeId: "",
  awayId: "",
  kickoff: "",
  name: "",
  venue: "",
  seasonType: "preseason",
  neutralSite: false,
}

const SEASON_LABELS: Record<string, string> = {
  preseason: "Preseason",
  regular: "Regular",
  postseason: "Postseason",
}

function formatKickoff(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function teamLabel(t: CachedTeam): string {
  return t.team_abbrev ? `${t.team_name} (${t.team_abbrev})` : t.team_name
}

/** Same two sides (either orientation) already listed upstream on this date. */
function findUpstreamDuplicate(
  hits: EventSearchHit[],
  homeName: string,
  awayName: string
): EventSearchHit | undefined {
  const norm = (s: string) => s.toLowerCase().trim()
  const pair = new Set([norm(homeName), norm(awayName)])
  return hits.find((h) => {
    if (h.event_id.startsWith("manual:")) return false
    if (!h.home_team || !h.away_team) return false
    const upstream = new Set([norm(h.home_team), norm(h.away_team)])
    return upstream.size === pair.size && [...pair].every((n) => upstream.has(n))
  })
}

interface EventFormProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Present = edit mode; the form pre-fills and PUTs instead of POSTing. */
  editing: ManualEvent | null
}

function EventForm({ open, onOpenChange, editing }: EventFormProps) {
  // Keyed by editing?.id in the parent so each open/edit session mounts
  // fresh from props — no setState-during-render, no stale reset (#1131 review).
  const [form, setForm] = useState<FormState>(() => initialForm(editing))
  const [formError, setFormError] = useState<string | null>(null)

  const pickerLeagues = useQuery({
    queryKey: ["team-picker-leagues"],
    queryFn: getTeamPickerLeagues,
    enabled: open,
    staleTime: 1000 * 60 * 5,
  })
  const configuredTeamVsTeamLeagues = useMemo(
    () =>
      (pickerLeagues.data?.leagues ?? []).filter(
        (l) => l.is_configured && l.event_type === "team_vs_team" && l.team_count >= 2
      ),
    [pickerLeagues.data]
  )

  const leagueTeams = useQuery({
    queryKey: ["league-teams", form.league],
    queryFn: () => getLeagueTeams(form.league),
    enabled: open && form.league !== "",
    staleTime: 1000 * 60 * 5,
  })

  const leagueMeta = configuredTeamVsTeamLeagues.find((l) => l.slug === form.league)
  const teams = leagueTeams.data ?? []
  const home = teams.find((t) => `${t.provider}:${t.provider_team_id}` === form.homeId)
  const away = teams.find((t) => `${t.provider}:${t.provider_team_id}` === form.awayId)

  // Upstream duplicate check (#1131): as soon as both sides and a date are
  // picked, look for the same fixture on provider schedules. The kickoff input
  // is browser-local while the backend resolves target_date in the Teamarr
  // timezone — the two calendars can disagree by a day, so fetch BOTH days and
  // merge rather than slicing the raw local string (#1131 review).
  const targetDate = form.kickoff ? form.kickoff.slice(0, 10) : ""
  const previousDate = targetDate
    ? new Date(`${targetDate}T12:00:00`)
    : null
  const dayBefore = previousDate
    ? new Date(previousDate.getTime() - 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
    : ""
  const upstream = useQuery({
    queryKey: ["manual-events", "upstream", form.league, dayBefore, targetDate],
    queryFn: async () => {
      const search = (date: string) =>
        api
          .get<{ events: EventSearchHit[] }>(
            `/epg/events/search?league=${encodeURIComponent(form.league)}&target_date=${date}&limit=200`
          )
          .catch(() => ({ events: [] as EventSearchHit[] }))
      const [today, yesterday] = await Promise.all([search(targetDate), search(dayBefore)])
      const seen = new Set<string>()
      return {
        events: [...yesterday.events, ...today.events].filter((e) =>
          seen.has(e.event_id) ? false : (seen.add(e.event_id), true)
        ),
      }
    },
    enabled:
      open &&
      form.league !== "" &&
      targetDate !== "" &&
      home !== undefined &&
      away !== undefined,
    staleTime: 1000 * 60 * 5,
  })
  const duplicate =
    home && away && upstream.data
      ? findUpstreamDuplicate(upstream.data.events, home.team_name, away.team_name)
      : undefined

  const create = useCreateManualEvent()
  const update = useUpdateManualEvent()
  const pending =
    create.isPending || update.isPending || pickerLeagues.isPending || leagueTeams.isPending

  const submit = () => {
    setFormError(null)
    if (!leagueMeta || !home || !away) {
      setFormError("Pick a league and two different teams from it.")
      return
    }
    if (form.homeId === form.awayId) {
      setFormError("Home and away teams must be different.")
      return
    }
    const kickoffDate = new Date(form.kickoff)
    if (Number.isNaN(kickoffDate.getTime())) {
      setFormError("Pick a date and start time.")
      return
    }
    const payload: ManualEventInput = {
      league: form.league,
      home_team: { provider: home.provider, id: home.provider_team_id },
      away_team: { provider: away.provider, id: away.provider_team_id },
      start_time: kickoffDate.toISOString(),
      name: form.name.trim() || null,
      venue: form.venue.trim() || null,
      season_type: form.seasonType,
      neutral_site: form.neutralSite,
    }
    const request = editing
      ? update.mutateAsync({ eventId: editing.id, data: payload })
      : create.mutateAsync(payload)
    request
      .then(() => {
        toast.success(editing ? "Event updated" : "Event added")
        onOpenChange(false)
      })
      .catch((err: Error) => setFormError(err.message))
  }

  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit Manual Event" : "Add Manual Event"}</DialogTitle>
          <DialogDescription>
            Add a game missing from the schedules — a preseason fixture, for example. The next
            generation matches it like any other event and creates a temporary channel when a
            stream is available.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {formError && (
            <Alert variant="destructive" title="Could not save">
              {formError}
            </Alert>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="me-league">League</Label>
            <Select
              id="me-league"
              value={form.league}
              disabled={pickerLeagues.isPending || configuredTeamVsTeamLeagues.length === 0}
              onChange={(e) => set({ league: e.target.value, homeId: "", awayId: "" })}
            >
              <option value="">
                {pickerLeagues.isPending ? "Loading leagues…" : "Pick a league…"}
              </option>
              {configuredTeamVsTeamLeagues.map((l) => (
                <option key={l.slug} value={l.slug}>
                  {l.name} — {l.sport_display_name}
                </option>
              ))}
            </Select>
            {!pickerLeagues.isPending && configuredTeamVsTeamLeagues.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No configured team-vs-team leagues have cached teams yet. Run a cache refresh
                first.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="me-home">Home team</Label>
              <Select
                id="me-home"
                value={form.homeId}
                disabled={!form.league || leagueTeams.isPending}
                onChange={(e) => set({ homeId: e.target.value })}
              >
                <option value="">
                  {leagueTeams.isPending ? "Loading teams…" : "Pick a team…"}
                </option>
                {teams.map((t) => (
                  <option key={`${t.provider}:${t.provider_team_id}`} value={`${t.provider}:${t.provider_team_id}`}>
                    {teamLabel(t)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="me-away">Away team</Label>
              <Select
                id="me-away"
                value={form.awayId}
                disabled={!form.league || leagueTeams.isPending}
                onChange={(e) => set({ awayId: e.target.value })}
              >
                <option value="">
                  {leagueTeams.isPending ? "Loading teams…" : "Pick a team…"}
                </option>
                {teams.map((t) => (
                  <option key={`${t.provider}:${t.provider_team_id}`} value={`${t.provider}:${t.provider_team_id}`}>
                    {teamLabel(t)}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="me-kickoff">Start time (your timezone)</Label>
              <Input
                id="me-kickoff"
                type="datetime-local"
                value={form.kickoff}
                onChange={(e) => set({ kickoff: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="me-season">Season type</Label>
              <Select
                id="me-season"
                value={form.seasonType}
                onChange={(e) =>
                  set({ seasonType: e.target.value as FormState["seasonType"] })
                }
              >
                <option value="preseason">Preseason</option>
                <option value="regular">Regular season</option>
                <option value="postseason">Postseason</option>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="me-name">Custom title (optional)</Label>
            <Input
              id="me-name"
              value={form.name}
              placeholder={`${away?.team_name ?? "Away"} at ${home?.team_name ?? "Home"}`}
              onChange={(e) => set({ name: e.target.value })}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="me-venue">Venue (optional)</Label>
            <Input
              id="me-venue"
              value={form.venue}
              onChange={(e) => set({ venue: e.target.value })}
            />
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="me-neutral"
              checked={form.neutralSite}
              onCheckedChange={(v) => set({ neutralSite: v === true })}
            />
            <Label htmlFor="me-neutral" className="font-normal">
              Neutral site
            </Label>
          </div>

          {duplicate && (
            <Alert variant="warning" title="Possible duplicate" icon={<TriangleAlert />}>
              Upstream already lists <strong>{duplicate.event_name}</strong> on this date (
              {formatKickoff(duplicate.start_time)}). Adding a manual copy may create a duplicate
              channel — duplicate resolution is not automatic yet.
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={pending || !form.league}>
            {pending && <Spinner className="mr-1.5 h-4 w-4" />}
            {editing ? "Save Changes" : "Add Event"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** ISO instant → value for <input type="datetime-local"> in the local zone. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Blank form, or one pre-filled from the event being edited. */
function initialForm(editing: ManualEvent | null): FormState {
  if (!editing) return EMPTY_FORM
  return {
    league: editing.league,
    homeId: `${editing.home_team.provider}:${editing.home_team.id}`,
    awayId: `${editing.away_team.provider}:${editing.away_team.id}`,
    kickoff: toLocalInput(new Date(editing.start_time)),
    // Only blank when it still equals the generated default — never wipe a
    // real custom title (#1131 review; the startsWith("manual") heuristic
    // would eat titles like "Manual High School Showcase").
    name:
      editing.name === defaultEventName(editing) ? "" : editing.name,
    venue: editing.venue?.name ?? "",
    seasonType: (editing.season_type as FormState["seasonType"]) ?? "preseason",
    neutralSite: editing.neutral_site,
  }
}

/** What the backend would have generated: "at" hosted, "vs" soccer/neutral. */
function defaultEventName(e: ManualEvent): string {
  if (e.neutral_site || e.home_team.sport === "soccer") {
    return `${e.away_team.name} vs ${e.home_team.name}`
  }
  return `${e.away_team.name} at ${e.home_team.name}`
}

export function ManualEvents() {
  const events = useManualEvents()
  const duplicates = useManualEventDuplicates()
  const cancel = useCancelManualEvent()

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ManualEvent | null>(null)
  const [pendingCancel, setPendingCancel] = useState<ManualEvent | null>(null)

  const rows = useMemo(
    () =>
      [...(events.data?.events ?? [])].sort((a, b) => {
        // Cancelled last, then soonest first. Compare instants, not strings —
        // lexicographic order breaks across offset representations (#1131 review).
        if ((a.status.state === "cancelled") !== (b.status.state === "cancelled"))
          return a.status.state === "cancelled" ? 1 : -1
        return new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
      }),
    [events.data]
  )

  const openAdd = () => {
    setEditing(null)
    setFormOpen(true)
  }
  const openEdit = (event: ManualEvent) => {
    setEditing(event)
    setFormOpen(true)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Manual Events</h2>
          <p className="text-sm text-muted-foreground">
            Add team games missing from the schedules (preseason fixtures, for example). They
            match streams and generate temporary event channels like any other event — no
            provider event required.
          </p>
        </div>
        <Button onClick={openAdd}>
          <CalendarPlus className="mr-1.5 h-4 w-4" />
          Add Event
        </Button>
      </div>

      {duplicates.data && duplicates.data.total > 0 && (
        <Alert
          variant="warning"
          title={`${duplicates.data.total} manual event${duplicates.data.total > 1 ? "s" : ""} also exist upstream`}
          icon={<TriangleAlert />}
        >
          <div className="space-y-2">
            <p>
              These fixtures are also on the provider schedules. Two candidates for the same
              game can produce duplicate channels. Removing the manual copy keeps the upstream
              event — channels from it are handled by normal generation.
            </p>
            {duplicates.data.duplicates.map((pair) => (
              <div
                key={pair.manual.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-yellow-500/30 bg-background/50 px-2.5 py-1.5 text-sm"
              >
                <span>
                  <strong>{pair.manual.name}</strong>
                  {pair.manual.status.state === "scheduled" && (
                    <span className="text-muted-foreground">
                      {" "}
                      — also listed as {pair.upstream.name} (
                      {formatKickoff(pair.upstream.start_time)})
                    </span>
                  )}
                </span>
                {pair.manual.status.state === "scheduled" && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPendingCancel(pair.manual)}
                  >
                    Remove manual copy
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Added Events</CardTitle>
          <CardDescription>
            Cancelled events stay listed for reference but never match again. Channels are
            created and retired by normal generation runs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {events.isPending ? (
            <div className="flex justify-center py-8">
              <Spinner className="h-6 w-6" />
            </div>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No manual events yet. Use <strong>Add Event</strong> to add a missing game.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Matchup</TableHead>
                  <TableHead>League</TableHead>
                  <TableHead>Start</TableHead>
                  <TableHead>Season</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((e) => (
                  <TableRow key={e.id} className={e.status.state === "cancelled" ? "opacity-50" : ""}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {e.away_team.logo_url && (
                          <img src={e.away_team.logo_url} alt="" className="h-5 w-5 object-contain" />
                        )}
                        <span className="font-medium">
                          {e.away_team.name} at {e.home_team.name}
                        </span>
                        {e.home_team.logo_url && (
                          <img src={e.home_team.logo_url} alt="" className="h-5 w-5 object-contain" />
                        )}
                      </div>
                      {e.name !== defaultEventName(e) && (
                        <div className="text-xs text-muted-foreground">{e.name}</div>
                      )}
                    </TableCell>
                    <TableCell className="uppercase text-xs">{e.league}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatKickoff(e.start_time)}</TableCell>
                    <TableCell>
                      {e.season_type && (
                        <Badge variant="outline">{SEASON_LABELS[e.season_type] ?? e.season_type}</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={e.status.state === "cancelled" ? "destructive" : "success"}>
                        {e.status.state === "cancelled" ? "Cancelled" : "Scheduled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {e.status.state === "scheduled" && (
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openEdit(e)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setPendingCancel(e)}
                            aria-label={`Cancel ${e.name}`}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Keyed remount: each open/edit session initializes from its props. */}
      <EventForm
        key={editing?.id ?? "new"}
        open={formOpen}
        onOpenChange={setFormOpen}
        editing={editing}
      />

      <ConfirmDialog
        open={pendingCancel !== null}
        onOpenChange={(open) => !open && setPendingCancel(null)}
        title="Cancel manual event"
        description={
          pendingCancel
            ? `Cancel "${pendingCancel.name}"? It stops matching immediately. The event stays listed here as cancelled, and the next generation run removes its channel.`
            : ""
        }
        confirmLabel="Cancel Event"
        isPending={cancel.isPending}
        onConfirm={() => {
          if (!pendingCancel) return
          cancel.mutate(
            { eventId: pendingCancel.id, league: pendingCancel.league },
            {
              onSuccess: () => {
                toast.success("Event cancelled")
                setPendingCancel(null)
              },
              onError: (err: Error) => toast.error(err.message),
            }
          )
        }}
      />
    </div>
  )
}
