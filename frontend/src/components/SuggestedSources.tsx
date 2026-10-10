import { useState } from "react"
import { toast } from "sonner"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, RefreshCw, Sparkles, Undo2, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { Switch } from "@/components/ui/switch"
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

const TIER_BADGE: Record<SuggestionTier, { label: string; variant: "success" | "info" | "outline" }> = {
  games: { label: "Events found", variant: "success" },
  teams: { label: "Team streams", variant: "info" },
  name_only: { label: "Name only", variant: "outline" },
}

/**
 * Suggested sources (#997): M3U groups that are not sources but carry — or by
 * their name should carry — games in subscribed leagues. Found by a scan that
 * runs once a day while the "Scan daily" switch in the header is on (#1027:
 * no cron to set, the tiers read a week of evidence); accepting one creates a
 * managed source, which is retired on its own when it goes quiet. Hand-made
 * sources are never touched. The auto-add stream cap lives with the automatic
 * mode toggles on the Subscriptions page.
 */
export function SuggestedSources({ leagueName }: { leagueName: LeagueName }) {
  const queryClient = useQueryClient()
  const [showDismissed, setShowDismissed] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const { data: schedulerData } = useSchedulerSettings()
  const updateScheduler = useUpdateSchedulerSettings()

  const scanDaily = schedulerData ? schedulerData.source_discovery_mode !== "off" : true

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

  const setScanDaily = (on: boolean) =>
    updateScheduler.mutate(
      { source_discovery_mode: on ? "suggest" : "off" },
      { onSuccess: () => toast.success(on ? "Daily scan on" : "Daily scan off"), onError },
    )

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
  const listed = new Set(open.map((c) => c.id))
  const selectedIds = [...selected].filter((id) => listed.has(id))

  // Flat list, one block per M3U account (the API returns it in that order).
  const byAccount = new Map<string, SourceCandidate[]>()
  for (const c of open) {
    const account = c.m3u_account_name ?? "Unknown account"
    byAccount.set(account, [...(byAccount.get(account) ?? []), c])
  }

  const row = (c: SourceCandidate) => (
    <div key={c.id} className="flex items-center gap-3 px-3 py-2 text-sm">
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
          {c.status === "dismissed" ? (
            <Badge variant="secondary" className="text-xs">Dismissed</Badge>
          ) : (
            c.tier && (
              <Badge variant={TIER_BADGE[c.tier].variant} className="text-xs">
                {TIER_BADGE[c.tier].label}
              </Badge>
            )
          )}
          <span className="text-xs text-muted-foreground">{c.stream_count} streams</span>
        </div>
        {c.tier && (
          <div className="text-xs text-muted-foreground">
            {evidenceText(c, leagueName)}
            {c.same_events_as && ` · same events as ${c.same_events_as}`}
            {c.status !== "dismissed" && c.auto_hold && ` · not added automatically: ${c.auto_hold}`}
          </div>
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
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Scan daily
            <Switch
              checked={scanDaily}
              disabled={!schedulerData || updateScheduler.isPending}
              onCheckedChange={setScanDaily}
              aria-label="Scan for sources once a day"
            />
          </label>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => scan.mutate()}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${busy ? "animate-spin" : ""}`} />
            {scanState?.running
              ? scanState.progress
                ? `Scanning ${scanState.progress.done + 1} of ${scanState.progress.total}`
                : "Scanning…"
              : "Scan now"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3 pt-2">
        <p className="text-xs text-muted-foreground">
          Once a day, Teamarr looks through every M3U group that is not already a source and
          suggests the ones carrying events in leagues you subscribe to, listed by the M3U account
          they come from. Replay groups are left out. Switch a league or sport to automatic under
          Subscriptions → Find sources automatically and its groups are added without asking,
          once they have shown events on two different days. Discovery reads stream names only: it does not use
          EPG matching, so linear channels such as ESPN or TSN1 are never suggested. Add those
          as an EPG-matching source yourself, or select their channel group under Matching →
          Dispatcharr as a Stream Source. A source added from here is{" "}
          <span className="font-medium">managed</span>: it is switched off when it has matched
          nothing for two weeks and back on when its group has games again. Sources you add or
          edit yourself are never changed.
        </p>

        {last && (
          <p className="text-xs text-muted-foreground">
            {last.error
              ? `Last scan failed: ${last.error}`
              : `Last scan: ${last.groups_scanned ?? 0} groups in ${last.duration_seconds ?? 0}s, ${
                  last.groups_with_games ?? 0
                } carrying subscribed events${
                  last.sources_auto_added ? `, ${last.sources_auto_added} added automatically` : ""
                }.`}
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

        {[...byAccount.entries()].map(([account, rows]) => {
          const ids = rows.map((c) => c.id)
          const allSelected = ids.every((id) => selected.has(id))
          return (
            <div key={account} className="space-y-1">
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
                  aria-label={`Select all from ${account}`}
                />
                {account} ({rows.length})
              </div>
              <div className="divide-y divide-border rounded-lg border border-border">
                {rows.map((c) => row(c))}
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
