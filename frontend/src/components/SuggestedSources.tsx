import { useState } from "react"
import { toast } from "sonner"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, RefreshCw, Sparkles, Undo2, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SaveButton } from "@/components/ui/save-button"
import { Switch } from "@/components/ui/switch"
import { CronPreview } from "@/components/CronPreview"
import { useSchedulerSettings, useUpdateSchedulerSettings } from "@/hooks/useSettings"
import {
  acceptSourceCandidate,
  dismissSourceCandidate,
  getSourceCandidates,
  restoreSourceCandidate,
  startDiscoveryScan,
  type SourceCandidate,
  type SuggestionTier,
} from "@/api/sourceDiscovery"

const QUERY_KEY = ["source-discovery", "candidates"]

type LeagueName = (slug: string) => string

function leagueCounts(counts: Record<string, number>, leagueName: LeagueName): string {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([slug, n]) => `${leagueName(slug)} ${n}`)
    .join(", ")
}

function evidenceText(c: SourceCandidate, leagueName: LeagueName): string {
  if (c.tier === "games") {
    const days = c.days_matched > 1 ? ` on ${c.days_matched} days` : ""
    return `${c.best_game_matches} streams matched events${days} (${leagueCounts(c.leagues, leagueName)})`
  }
  if (c.tier === "teams") {
    return `Team streams: ${leagueCounts(c.team_leagues, leagueName)}`
  }
  if (c.tier === "name_only") {
    return `Name mentions ${c.name_leagues.map(leagueName).join(", ")}; no events seen yet`
  }
  return ""
}

const SECTIONS: { tier: SuggestionTier; title: string }[] = [
  { tier: "games", title: "Events found" },
  { tier: "teams", title: "Team streams" },
  { tier: "name_only", title: "Name only" },
]

/**
 * Suggested sources (#997): M3U groups that are not sources but carry — or by
 * their name should carry — games in subscribed leagues. Found by a scan that
 * runs on its own schedule; accepting one creates a managed source, which is
 * retired on its own when it goes quiet. Hand-made sources are never touched.
 */
export function SuggestedSources({ leagueName }: { leagueName: LeagueName }) {
  const queryClient = useQueryClient()
  const [showDismissed, setShowDismissed] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const { data: schedulerData } = useSchedulerSettings()
  const updateScheduler = useUpdateSchedulerSettings()

  const [enabled, setEnabled] = useState(false)
  const [cron, setCron] = useState("")
  const [synced, setSynced] = useState<typeof schedulerData>(undefined)
  if (schedulerData && schedulerData !== synced) {
    setSynced(schedulerData)
    setEnabled(schedulerData.source_discovery_mode !== "off")
    setCron(schedulerData.source_discovery_cron ?? "")
  }

  const { data } = useQuery({
    queryKey: [...QUERY_KEY, showDismissed],
    queryFn: () => getSourceCandidates(showDismissed),
    // Poll only while a scan is running, to show progress and then its results.
    refetchInterval: (query) => (query.state.data?.scan.running ? 3000 : false),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    queryClient.invalidateQueries({ queryKey: ["groups"] })
  }
  const onError = (err: unknown) =>
    toast.error(err instanceof Error ? err.message : "Request failed")

  const scan = useMutation({
    mutationFn: startDiscoveryScan,
    onSuccess: () => {
      toast.success("Scan started")
      refresh()
    },
    onError,
  })
  const accept = useMutation({
    mutationFn: acceptSourceCandidate,
    onSuccess: () => {
      toast.success("Added as a managed source")
      refresh()
    },
    onError,
  })
  const dismiss = useMutation({ mutationFn: dismissSourceCandidate, onSuccess: refresh, onError })
  const restore = useMutation({ mutationFn: restoreSourceCandidate, onSuccess: refresh, onError })

  const saveSchedule = async () => {
    try {
      await updateScheduler.mutateAsync({
        source_discovery_mode: enabled ? "suggest" : "off",
        source_discovery_cron: cron,
      })
      toast.success("Source discovery settings saved")
    } catch (err) {
      onError(err)
    }
  }

  // Bulk add / dismiss: one request per group, then one refresh.
  const bulk = useMutation({
    mutationFn: async ({ ids, action }: { ids: number[]; action: "add" | "dismiss" }) => {
      for (const id of ids) {
        await (action === "add" ? acceptSourceCandidate(id) : dismissSourceCandidate(id))
      }
      return { count: ids.length, action }
    },
    onSuccess: ({ count, action }) => {
      toast.success(
        action === "add" ? `Added ${count} managed sources` : `Dismissed ${count} groups`,
      )
      setSelected(new Set())
    },
    onError,
    onSettled: refresh,
  })

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const candidates = data?.candidates ?? []
  const open = candidates.filter((c) => c.status !== "dismissed")
  const dismissed = candidates.filter((c) => c.status === "dismissed")
  // Only what is still listed can be acted on (a refresh may have removed rows).
  const listed = new Set(open.flatMap((c) => [c.id, ...c.alternates.map((a) => a.id)]))
  const selectedIds = [...selected].filter((id) => listed.has(id))

  const row = (c: SourceCandidate, alternate = false) => (
    <div
      key={c.id}
      className={`flex items-center gap-3 px-3 py-2 text-sm ${alternate ? "pl-10 bg-muted/30" : ""}`}
    >
      {c.status !== "dismissed" && (
        <Checkbox
          checked={selected.has(c.id)}
          onCheckedChange={() => toggle(c.id)}
          aria-label={`Select ${c.m3u_group_name}`}
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium truncate">{c.m3u_group_name}</span>
          {alternate && (
            <Badge variant="outline" className="text-xs">Same events</Badge>
          )}
          {c.status === "dismissed" && (
            <Badge variant="secondary" className="text-xs">Dismissed</Badge>
          )}
          <span className="text-xs text-muted-foreground">{c.stream_count} streams</span>
        </div>
        {c.tier && (
          <div className="text-xs text-muted-foreground">{evidenceText(c, leagueName)}</div>
        )}
      </div>
      {c.status === "dismissed" ? (
        <Button size="sm" variant="ghost" onClick={() => restore.mutate(c.id)}>
          <Undo2 className="h-3.5 w-3.5 mr-1" />
          Restore
        </Button>
      ) : (
        <>
          <Button size="sm" disabled={accept.isPending} onClick={() => accept.mutate(c.id)}>
            <Check className="h-3.5 w-3.5 mr-1" />
            Add
          </Button>
          <Button
            size="sm"
            variant="ghost"
            title="Don't suggest this group again"
            onClick={() => dismiss.mutate(c.id)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </>
      )}
    </div>
  )
  const scanState = data?.scan
  const busy = scan.isPending || !!scanState?.running
  const last = scanState?.last

  return (
    <CollapsibleSection
      title="Suggested sources"
      icon={<Sparkles className="h-4 w-4" />}
      count={open.length > 0 ? `(${open.length})` : undefined}
      variant="subsection"
      persistKey="sources.suggested"
      actions={
        <Button size="sm" variant="outline" disabled={busy} onClick={() => scan.mutate()}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${busy ? "animate-spin" : ""}`} />
          {scanState?.running
            ? scanState.progress
              ? `Scanning ${scanState.progress.done + 1} of ${scanState.progress.total}`
              : "Scanning…"
            : "Scan now"}
        </Button>
      }
    >
      <div className="space-y-3 pt-2">
        <p className="text-xs text-muted-foreground">
          Teamarr can look through every M3U group that is not already a source and suggest the
          ones carrying events in leagues you subscribe to. Replay groups are left out, and
          groups carrying the same events are shown together. A source added from here is{" "}
          <span className="font-medium">managed</span>: it is switched off when it has matched
          nothing for two weeks and back on when its group has games again. Sources you add or
          edit yourself are never changed.
        </p>

        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border p-3">
          <div className="flex items-center gap-2">
            <Switch id="discovery-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="discovery-enabled">Scan on a schedule</Label>
          </div>
          <div className="space-y-1">
            <Label htmlFor="discovery-cron" className="text-xs">
              Schedule (cron expression)
            </Label>
            <Input
              id="discovery-cron"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              disabled={!enabled}
              className="font-mono h-8 w-40"
              placeholder="0 11 * * *"
            />
          </div>
          <div className="text-xs pb-1.5">{enabled && <CronPreview expression={cron} />}</div>
          <div className="ml-auto">
            <SaveButton onClick={saveSchedule} pending={updateScheduler.isPending} />
          </div>
        </div>

        {last && (
          <p className="text-xs text-muted-foreground">
            {last.error
              ? `Last scan failed: ${last.error}`
              : `Last scan: ${last.groups_scanned ?? 0} groups in ${last.duration_seconds ?? 0}s, ${
                  last.groups_with_games ?? 0
                } carrying subscribed games.`}
          </p>
        )}

        {selectedIds.length > 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
            <span>{selectedIds.length} selected</span>
            <Button
              size="sm"
              disabled={bulk.isPending}
              onClick={() => bulk.mutate({ ids: selectedIds, action: "add" })}
            >
              <Check className="h-3.5 w-3.5 mr-1" />
              Add selected
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={bulk.isPending}
              onClick={() => bulk.mutate({ ids: selectedIds, action: "dismiss" })}
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Dismiss selected
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        )}

        {open.length === 0 && (
          <p className="text-sm text-muted-foreground py-2">
            Nothing to suggest yet. A group is suggested once a scan has seen events in it, so the
            list fills in over the first few days.
          </p>
        )}

        {SECTIONS.map(({ tier, title }) => {
          const rows = open.filter((c) => c.tier === tier)
          if (rows.length === 0) return null
          const ids = rows.flatMap((c) => [c.id, ...c.alternates.map((a) => a.id)])
          const allSelected = ids.every((id) => selected.has(id))
          return (
            <div key={tier} className="space-y-1">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={() =>
                    setSelected((prev) => {
                      const next = new Set(prev)
                      for (const id of ids) {
                        if (allSelected) next.delete(id)
                        else next.add(id)
                      }
                      return next
                    })
                  }
                  aria-label={`Select all in ${title}`}
                />
                {title} ({rows.length})
              </div>
              <div className="divide-y divide-border rounded-lg border border-border max-h-96 overflow-y-auto">
                {rows.flatMap((c) => [row(c), ...c.alternates.map((a) => row(a, true))])}
              </div>
            </div>
          )
        })}

        {dismissed.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Dismissed ({dismissed.length})
            </div>
            <div className="divide-y divide-border rounded-lg border border-border max-h-96 overflow-y-auto">
              {dismissed.map((c) => row(c))}
            </div>
          </div>
        )}

        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={showDismissed} onCheckedChange={setShowDismissed} />
          Show dismissed groups
        </label>
      </div>
    </CollapsibleSection>
  )
}
