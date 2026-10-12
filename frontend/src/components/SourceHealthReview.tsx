import { useState } from "react"
import { toast } from "sonner"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, CircleAlert, Eye, Undo2 } from "lucide-react"
import { getSourceHealth, keepSourceHealthRecommendation, restoreSourceHealthRecommendation, snoozeSourceHealthRecommendation, type SourceHealthRecommendation } from "@/api/sourceHealth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CollapsibleSection } from "@/components/ui/collapsible-section"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useToggleGroup } from "@/hooks/useGroups"
import { useDateFormat } from "@/hooks/useDateFormat"

type LeagueName = (slug: string) => string

const QUERY_KEY = ["source-health", "recommendations"]

function kindLabel(recommendation: SourceHealthRecommendation): string {
  return recommendation.kind === "quiet" ? "Quiet in season" : "Low match coverage"
}

export function SourceHealthReview({
  leagueName,
  onEdit,
}: {
  leagueName: LeagueName
  onEdit: (groupId: number) => void
}) {
  const queryClient = useQueryClient()
  const [showHidden, setShowHidden] = useState(false)
  const [disableTarget, setDisableTarget] = useState<SourceHealthRecommendation | null>(null)
  const { formatRelativeTime } = useDateFormat()
  const toggleGroup = useToggleGroup()
  const { data, isLoading, error } = useQuery({
    queryKey: [...QUERY_KEY, showHidden],
    queryFn: () => getSourceHealth(showHidden),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    queryClient.invalidateQueries({ queryKey: ["groups"] })
  }
  const onError = (err: unknown) =>
    toast.error(err instanceof Error ? err.message : "Request failed")
  const keep = useMutation({
    mutationFn: keepSourceHealthRecommendation,
    onSuccess: () => {
      toast.success("Kept; it will return if this source matches again")
      refresh()
    },
    onError,
  })
  const snooze = useMutation({
    mutationFn: snoozeSourceHealthRecommendation,
    onSuccess: () => {
      toast.success("Source review snoozed for 30 days")
      refresh()
    },
    onError,
  })
  const restore = useMutation({
    mutationFn: restoreSourceHealthRecommendation,
    onSuccess: refresh,
    onError,
  })

  const recommendations = data?.recommendations ?? []
  const activeCount = recommendations.filter((item) => !item.decision).length
  const busy = keep.isPending || snooze.isPending || restore.isPending || toggleGroup.isPending

  if (!isLoading && !error && recommendations.length === 0 && !data?.hidden_count) {
    return null
  }

  const row = (item: SourceHealthRecommendation) => {
    const hidden = item.decision !== null
    const matchingMethods = Object.entries(item.matching_types)
      .filter(([, enabled]) => enabled)
      .map(([kind]) => kind.toUpperCase())
      .join(" + ")
    return (
      <div key={item.group_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b py-3 last:border-b-0">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{item.group_name}</span>
            <Badge variant={item.kind === "quiet" ? "info" : "warning"} className="text-xs">
              {kindLabel(item)}
            </Badge>
            {item.leagues.map((league) => (
              <Badge key={league} variant="outline" className="text-xs">
                {leagueName(league)}
              </Badge>
            ))}
            {hidden && (
              <Badge variant="secondary" className="text-xs">
                {item.decision === "keep" ? "Kept" : "Snoozed"}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {item.reason}. Evidence: {item.sample_runs} successful runs over {item.sample_days} days
            {item.coverage !== null && ` · ${Math.round(item.coverage * 100)}% matched`}
            {matchingMethods && ` · ${matchingMethods} matching`}
            {item.last_matched_at && ` · last match ${formatRelativeTime(item.last_matched_at)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {hidden ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => restore.mutate(item.group_id)}>
              <Undo2 className="mr-1 h-3.5 w-3.5" />
              Restore
            </Button>
          ) : (
            <>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onEdit(item.group_id)}>
                Review
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} title="Keep hidden until this source matches again" onClick={() => keep.mutate(item.group_id)}>
                Keep
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => snooze.mutate(item.group_id)}>
                Snooze 30d
              </Button>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => setDisableTarget(item)}
              >
                Disable
              </Button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <CollapsibleSection
      title="Review sources"
      icon={<Activity className="h-4 w-4" />}
      count={activeCount ? `(${activeCount})` : undefined}
      actions={data?.hidden_count ? (
        <Button size="sm" variant="ghost" onClick={() => setShowHidden((value) => !value)}>
          <Eye className="mr-1 h-3.5 w-3.5" />
          {showHidden ? "Hide kept/snoozed" : `Show kept/snoozed (${data.hidden_count})`}
        </Button>
      ) : undefined}
      persistKey="sources.health"
    >
      <div className="space-y-2 pt-2">
        <p className="text-xs text-muted-foreground">
          These are review suggestions, never automatic changes. Teamarr waits for repeated successful runs,
          enough eligible streams, and recent league event evidence; empty feeds and provider-fetch failures
          are not treated as a bad source. Expected NFL, NHL, and MLB offseason quiet is not flagged. Missing
          M3U groups appear separately above.
        </p>
        {error ? (
          <div className="flex items-center gap-2 py-3 text-sm text-destructive">
            <CircleAlert className="h-4 w-4" />
            Could not load source-health recommendations.
          </div>
        ) : isLoading ? (
          <p className="py-3 text-sm text-muted-foreground">Checking source history…</p>
        ) : recommendations.length ? (
          <div>{recommendations.map(row)}</div>
        ) : (
          <p className="py-3 text-sm text-muted-foreground">
            No sources need review based on recent in-season runs.
          </p>
        )}
      </div>
      <ConfirmDialog
        open={disableTarget !== null}
        onOpenChange={(open) => !open && setDisableTarget(null)}
        title={`Disable ${disableTarget?.group_name ?? "source"}?`}
        description="This stops Teamarr from processing this source. Its settings and existing channels are kept."
        confirmLabel="Disable source"
        isPending={toggleGroup.isPending}
        onConfirm={() => {
          if (!disableTarget) return
          toggleGroup.mutate(
            { groupId: disableTarget.group_id, enabled: false },
            {
              onSuccess: () => {
                toast.success(`Disabled ${disableTarget.group_name}`)
                setDisableTarget(null)
                refresh()
              },
              onError,
            },
          )
        }}
      />
    </CollapsibleSection>
  )
}
