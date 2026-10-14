import { useState } from "react"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import { CircleAlert, Timer, Trash2, Workflow } from "lucide-react"
import { Button } from "@/components/ui/button"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSchedulerSettings, useUpdateSchedulerSettings } from "@/hooks/useSettings"
import { useDeleteGroup } from "@/hooks/useGroups"
import { useDateFormat } from "@/hooks/useDateFormat"
import { getStaleGroups } from "@/api/groups"
import { SuggestedSources } from "@/components/SuggestedSources"
import { AutoSourceToggles } from "@/components/AutoSourceToggles"

type LeagueName = (slug: string) => string

/**
 * Everything Teamarr does to the source list on its own, in one place and in
 * the order it happens (#1058): discover groups that carry games, add them for
 * toggled leagues, retire discovered sources that go quiet, remove sources
 * whose Dispatcharr group is gone. The rules are settings, read as one policy
 * by the daily scan and by every generation run.
 */
export function SourceAutomation({ leagueName }: { leagueName: LeagueName }) {
  return (
    <CollapsibleSection
      title="Automation"
      icon={<Workflow className="h-5 w-5" />}
      variant="section"
      persistKey="sources.automation"
    >
      <div className="space-y-4 pt-2">
        <p className="text-xs text-muted-foreground">
          What Teamarr does to your source list on its own, in the order it happens. Sources you
          add or edit yourself are only ever touched by the last rule, and only if you switch it
          on.
        </p>
        <SuggestedSources leagueName={leagueName} />
        <AutoSourceToggles />
        <RetireRules />
        <RemoveMissing />
      </div>
    </CollapsibleSection>
  )
}

/** A whole-number setting edited locally and saved on blur / Enter. */
function DaysField({
  id,
  label,
  hint,
  value,
  min,
  onSave,
}: {
  id: string
  label: string
  hint: string
  value: number | undefined
  min: number
  onSave: (n: number) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? String(value ?? "")
  const commit = () => {
    const n = Number.parseInt(shown, 10)
    setDraft(null)
    if (!Number.isFinite(n) || n < min || n === value) return
    onSave(n)
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          min={min}
          value={shown}
          disabled={value === undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur()
          }}
          className="h-8 w-24"
        />
        <Label htmlFor={id} className="text-sm font-normal">
          {label}
        </Label>
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function useSavePolicy() {
  const update = useUpdateSchedulerSettings()
  return (patch: Parameters<typeof update.mutate>[0]) =>
    update.mutate(patch, {
      onError: (e) => toast.error(e instanceof Error ? e.message : "Failed to save"),
    })
}

/** Retire: the windows after which a discovered source is switched off and then removed. */
function RetireRules() {
  const { data: scheduler } = useSchedulerSettings()
  const save = useSavePolicy()
  return (
    <CollapsibleSection
      title="Retire"
      icon={<Timer className="h-4 w-4" />}
      variant="subsection"
      persistKey="sources.automation.retire"
    >
      <div className="space-y-3 pt-2">
        <p className="text-xs text-muted-foreground">
          A source added by discovery is marked <span className="font-medium">managed</span>. It
          is switched off when it stops matching, switched back on when a scan sees games in its
          group again, and removed once its group has been gone from Dispatcharr for a while. Its
          settings are kept until it is removed. Editing a managed source by hand makes it yours,
          and these rules stop applying to it.
        </p>
        <DaysField
          id="source-idle-days"
          label="days without a match before a discovered source is switched off"
          hint="Seven more days when the group's name still names a subscribed league."
          value={scheduler?.source_idle_days}
          min={1}
          onSave={(n) => save({ source_idle_days: n })}
        />
        <DaysField
          id="source-gone-days"
          label="days its group has been gone before a switched-off discovered source is removed"
          hint="Counted from the last scan that saw the group. If the group comes back, the source is added again without asking."
          value={scheduler?.source_gone_days}
          min={1}
          onSave={(n) => save({ source_gone_days: n })}
        />
      </div>
    </CollapsibleSection>
  )
}

/** Remove: sources whose M3U group is gone from Dispatcharr, and the rule that deletes them. */
function RemoveMissing() {
  const { data: scheduler } = useSchedulerSettings()
  const save = useSavePolicy()
  const { formatRelativeTime } = useDateFormat()
  const deleteMutation = useDeleteGroup()
  const { data: staleGroups = [] } = useQuery({
    queryKey: ["groups", "stale"],
    queryFn: getStaleGroups,
  })
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const deleteAll = async () => {
    setDeleting(true)
    try {
      const results = await Promise.allSettled(
        staleGroups.map((g) => deleteMutation.mutateAsync(g.id)),
      )
      const ok = results.filter((r) => r.status === "fulfilled").length
      const failed = results.length - ok
      if (failed === 0) toast.success(`Deleted ${ok} source${ok === 1 ? "" : "s"}`)
      else toast.warning(`Deleted ${ok}, failed ${failed}`)
      setConfirmOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete sources")
    } finally {
      setDeleting(false)
    }
  }

  const n = staleGroups.length
  return (
    <CollapsibleSection
      title="Remove"
      icon={<Trash2 className="h-4 w-4" />}
      count={n > 0 ? `(${n} missing)` : undefined}
      variant="subsection"
      persistKey="sources.automation.remove"
    >
      <div className="space-y-3 pt-2">
        <p className="text-xs text-muted-foreground">
          Every generation run checks that each source's M3U group still exists in Dispatcharr. A
          source whose group was removed or renamed can no longer pull streams; its channels stay
          until their normal expiry. Discovery suggests the group's replacement on its own when
          one carries games.
        </p>
        <DaysField
          id="source-missing-delete-days"
          label="days a source's group may be missing before the source is deleted (0 = never)"
          hint="Applies to sources you made yourself; discovered sources follow the Retire rules. Deleting removes the source's channels and settings, so this is off by default."
          value={scheduler?.source_missing_delete_days}
          min={0}
          onSave={(n) => save({ source_missing_delete_days: n })}
        />
        {n === 0 ? (
          <p className="text-sm text-muted-foreground">
            Every source's group is present in Dispatcharr.
          </p>
        ) : (
          <div className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <CircleAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              {n} source{n === 1 ? "" : "s"} missing from Dispatcharr
            </div>
            <ul className="space-y-1.5 text-sm">
              {staleGroups.map((g) => (
                <li key={g.id} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium">{g.display_name || g.name}</span>
                  {g.m3u_group_name && (
                    <span className="text-xs text-muted-foreground">
                      was &ldquo;{g.m3u_group_name}&rdquo;
                    </span>
                  )}
                  {g.source_last_seen && (
                    <span className="text-xs text-muted-foreground">
                      · last seen {formatRelativeTime(g.source_last_seen)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            <Button variant="destructive" size="sm" onClick={() => setConfirmOpen(true)}>
              <Trash2 className="h-4 w-4 mr-1" />
              Delete all missing
            </Button>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Delete ${n} missing source${n === 1 ? "" : "s"}`}
        description="These sources' M3U groups no longer exist in Dispatcharr. Deleting them also removes their managed channels. This cannot be undone."
        confirmLabel="Delete all missing"
        isPending={deleting}
        onConfirm={deleteAll}
      />
    </CollapsibleSection>
  )
}
