import { useMemo, useState } from "react"
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
import { useSports } from "@/hooks/useSports"
import { getSportDisplayName } from "@/lib/utils"
import {
  useCreateNumberingException,
  useDeleteNumberingException,
  useNumberingExceptions,
  useNumberingPreview,
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
 */

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

  const [addOpen, setAddOpen] = useState(false)

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
              Priority Teams above. Blocks spill forward if they fill up.
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
                className={`flex items-center gap-3 px-3 py-2 ${b.enabled ? "" : "opacity-60"}`}
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
                    {` · ${b.channel_count} channel${b.channel_count === 1 ? "" : "s"} today`}
                  </div>
                </div>
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
  const [showEnd, setShowEnd] = useState(false)

  const reset = () => {
    setScope("team")
    setTeam([])
    setLeagueCode("")
    setSport("")
    setStart("")
    setEnd("")
    setLabel("")
    setShowEnd(false)
  }

  // Joining an existing group pre-fills its start.
  const onLabelChange = (v: string) => {
    setLabel(v)
    const match = existing.find((b) => b.label === v)
    if (match && !start) setStart(String(match.start))
  }

  const startNum = parseInt(start)
  const endNum = end === "" ? null : parseInt(end)
  const valid =
    !isNaN(startNum) &&
    startNum >= 1 &&
    (endNum === null || (!isNaN(endNum) && endNum >= startNum)) &&
    (scope === "team" ? team.length === 1 : scope === "league" ? !!leagueCode : !!sport)

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

          {showEnd ? (
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
          ) : (
            <button
              type="button"
              className="text-xs text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => setShowEnd(true)}
            >
              Set an end channel (advanced)
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
