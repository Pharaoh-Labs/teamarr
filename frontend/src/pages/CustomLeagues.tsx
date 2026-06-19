import { useState } from "react"
import { toast } from "sonner"
import { AlertTriangle, FlaskConical, Loader2, Pencil, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError } from "@/api/client"
import type {
  CustomLeague,
  CustomLeagueCapability,
  CustomLeagueTestResult,
} from "@/api/customLeagues"
import {
  useCreateCustomLeague,
  useCustomLeagues,
  useDeleteCustomLeague,
  useTestCustomLeague,
  useUpdateCustomLeague,
} from "@/hooks/useCustomLeagues"

const EVENT_TYPES = [
  { value: "team_vs_team", label: "Team vs Team" },
  { value: "event_card", label: "Event Card (combat)" },
]

interface FormState {
  league_code: string
  provider_league_id: string
  provider_league_name: string
  display_name: string
  sport: string
  event_type: string
  allow_empty: boolean
}

const EMPTY_FORM: FormState = {
  league_code: "",
  provider_league_id: "",
  provider_league_name: "",
  display_name: "",
  sport: "",
  event_type: "team_vs_team",
  allow_empty: false,
}

function errMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

export function CustomLeaguesManager({
  capability,
}: {
  capability: CustomLeagueCapability | undefined
}) {
  const leaguesQuery = useCustomLeagues()
  const deleteMutation = useDeleteCustomLeague()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<CustomLeague | null>(null)

  const leagues = leaguesQuery.data?.custom_leagues ?? []

  const openAdd = () => {
    setEditing(null)
    setDialogOpen(true)
  }
  const openEdit = (league: CustomLeague) => {
    setEditing(league)
    setDialogOpen(true)
  }

  const handleDelete = async (league: CustomLeague) => {
    if (!confirm(`Delete custom league "${league.display_name}"?`)) return
    try {
      await deleteMutation.mutateAsync(league.league_code)
      toast.success(`Deleted ${league.display_name}`)
    } catch (err) {
      toast.error(errMessage(err, "Failed to delete league"))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={openAdd}>
          <Plus className="h-4 w-4" /> Add Custom League
        </Button>
      </div>

      {leagues.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No custom leagues yet. Click <span className="font-medium">Add Custom League</span> to
            create one.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>League</TableHead>
                  <TableHead>Code</TableHead>
                  <TableHead>Sport</TableHead>
                  <TableHead>TSDB ID</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leagues.map((league) => (
                  <TableRow key={league.league_code}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {league.display_name}
                        {!league.subscribed && (
                          <Badge
                            variant="warning"
                            title="This league isn't in your subscription, so its games won't appear. Add it under Subscriptions."
                          >
                            <AlertTriangle className="h-3 w-3" /> Not subscribed
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {league.league_code}
                    </TableCell>
                    <TableCell>{league.sport}</TableCell>
                    <TableCell className="font-mono text-xs">{league.provider_league_id}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(league)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(league)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {dialogOpen && (
        <CustomLeagueDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          capability={capability}
          editing={editing}
        />
      )}
    </div>
  )
}

function CustomLeagueDialog({
  open,
  onOpenChange,
  capability,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  capability: CustomLeagueCapability | undefined
  editing: CustomLeague | null
}) {
  const isEdit = editing !== null
  const [form, setForm] = useState<FormState>(
    editing
      ? {
          league_code: editing.league_code,
          provider_league_id: editing.provider_league_id,
          provider_league_name: editing.provider_league_name,
          display_name: editing.display_name,
          sport: editing.sport,
          event_type: editing.event_type,
          allow_empty: false,
        }
      : EMPTY_FORM
  )
  const [testResult, setTestResult] = useState<CustomLeagueTestResult | null>(null)

  const testMutation = useTestCustomLeague()
  const createMutation = useCreateCustomLeague()
  const updateMutation = useUpdateCustomLeague()

  const sports = capability?.supported_sports ?? []
  const set = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }))
    setTestResult(null) // any edit invalidates the prior test
  }

  const canTest = form.provider_league_id.trim() !== "" && form.sport !== ""

  const handleTest = async () => {
    try {
      const result = await testMutation.mutateAsync({
        provider_league_id: form.provider_league_id.trim(),
        sport: form.sport,
        provider_league_name: form.provider_league_name.trim() || undefined,
      })
      setTestResult(result)
      if (result.event_count === 0) {
        toast.warning("TheSportsDB returned no upcoming events for this league.")
      } else {
        toast.success(`Found ${result.event_count} upcoming event(s).`)
      }
    } catch (err) {
      toast.error(errMessage(err, "Test fetch failed"))
    }
  }

  const handleSave = async () => {
    try {
      if (isEdit) {
        await updateMutation.mutateAsync({
          leagueCode: editing.league_code,
          data: {
            provider_league_id: form.provider_league_id.trim(),
            provider_league_name: form.provider_league_name.trim(),
            display_name: form.display_name.trim(),
            sport: form.sport,
            event_type: form.event_type,
          },
        })
        toast.success("Custom league updated")
      } else {
        const result = await createMutation.mutateAsync({
          league_code: form.league_code.trim(),
          provider_league_id: form.provider_league_id.trim(),
          provider_league_name: form.provider_league_name.trim(),
          display_name: form.display_name.trim(),
          sport: form.sport,
          event_type: form.event_type,
          allow_empty: form.allow_empty,
        })
        const refresh = result.team_refresh
        if (refresh && refresh.success && refresh.team_count > 0) {
          toast.success(`Custom league created — cached ${refresh.team_count} team(s)`)
        } else if (refresh && !refresh.success) {
          toast.success("Custom league created — teams not cached yet (will retry on next refresh)")
        } else {
          toast.success("Custom league created")
        }
      }
      onOpenChange(false)
    } catch (err) {
      toast.error(errMessage(err, "Failed to save league"))
    }
  }

  const saving = createMutation.isPending || updateMutation.isPending
  const requiredFilled =
    form.provider_league_id.trim() &&
    form.provider_league_name.trim() &&
    form.display_name.trim() &&
    form.sport &&
    (isEdit || form.league_code.trim())

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Custom League" : "Add Custom League"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>League Code</Label>
              <Input
                placeholder="swe.1"
                value={form.league_code}
                disabled={isEdit}
                onChange={(e) => set({ league_code: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Unique id, e.g. <span className="font-mono">swe.1</span>. Can't be changed later.
              </p>
            </div>
            <div className="space-y-1">
              <Label>Display Name</Label>
              <Input
                placeholder="Allsvenskan"
                value={form.display_name}
                onChange={(e) => set({ display_name: e.target.value })}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>TSDB League ID</Label>
              <Input
                placeholder="4379"
                value={form.provider_league_id}
                onChange={(e) => set({ provider_league_id: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>TSDB League Name</Label>
              <Input
                placeholder="Swedish Allsvenskan"
                value={form.provider_league_name}
                onChange={(e) => set({ provider_league_name: e.target.value })}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Sport</Label>
              <Select value={form.sport} onChange={(e) => set({ sport: e.target.value })}>
                <option value="">Select…</option>
                {sports.map((s) => (
                  <option key={s.sport_code} value={s.sport_code}>
                    {s.display_name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Event Type</Label>
              <Select
                value={form.event_type}
                onChange={(e) => set({ event_type: e.target.value })}
              >
                {EVENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <HelpText />

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleTest}
              disabled={!canTest || testMutation.isPending}
            >
              {testMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FlaskConical className="h-4 w-4" />
              )}
              Test Fetch
            </Button>
            <span className="text-xs text-muted-foreground">
              Confirm the ID resolves and returns real fixtures before saving.
            </span>
          </div>

          {testResult && <TestResultPanel result={testResult} />}
        </div>

        <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
          {!isEdit && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={form.allow_empty}
                onChange={(e) => setForm((f) => ({ ...f, allow_empty: e.target.checked }))}
              />
              Save even if no events (off-season league)
            </label>
          )}
          <div className="flex gap-2 sm:ml-auto">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!requiredFilled || saving}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {isEdit ? "Save Changes" : "Create League"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TestResultPanel({ result }: { result: CustomLeagueTestResult }) {
  return (
    <Card className="bg-secondary/40">
      <CardContent className="space-y-2 pt-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="info">{result.tsdb_league_name ?? "Unknown league"}</Badge>
          <Badge variant="secondary">{result.tsdb_sport}</Badge>
          <Badge variant={result.event_count > 0 ? "success" : "warning"}>
            {result.event_count} upcoming event(s)
          </Badge>
          {result.name_matches === false && (
            <Badge variant="warning">Name differs from TheSportsDB</Badge>
          )}
        </div>
        {result.sample_events.length > 0 ? (
          <ul className="space-y-1">
            {result.sample_events.map((ev, i) => (
              <li key={i} className="text-muted-foreground">
                <span className="text-foreground">{ev.name ?? `${ev.home} vs ${ev.away}`}</span>
                {ev.date ? ` — ${ev.date}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">
            No upcoming fixtures. This may be an off-season league, or the ID may be wrong.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function HelpText() {
  return (
    <p className="rounded-md bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
      Find these on the league's <span className="font-medium">thesportsdb.com</span> page: the{" "}
      <span className="font-mono">idLeague</span> (TSDB League ID) is in the URL, and the exact{" "}
      <span className="font-mono">strLeague</span> (TSDB League Name) is the league's title — it
      must match TheSportsDB exactly. Use <span className="font-medium">Test Fetch</span> to
      confirm.
    </p>
  )
}
