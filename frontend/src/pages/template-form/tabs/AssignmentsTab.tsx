/**
 * AssignmentsTab — where THIS template is used, from the template's point of
 * view (#461, yk4j.15).
 *
 * Event templates: the global assignment rules pointing at this template,
 * with quick add/edit/delete scoped to it. The central Template Assignments
 * manager (Templates page) stays the cross-template conflict view.
 *
 * Team templates: the followed teams currently using this template —
 * per-team assignment stays on the Teams page.
 */

import { useMemo, useState, useCallback } from "react"
import { Link } from "react-router"
import { useQuery } from "@tanstack/react-query"
import { Plus, Pencil, Trash2, ExternalLink, LoaderCircle, Info } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { CheckboxListPicker } from "@/components/ui/checkbox-list-picker"
import type { CheckboxListGroup } from "@/components/ui/checkbox-list-picker"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import {
  useSubscription,
  useSubscriptionTemplates,
  useCreateSubscriptionTemplate,
  useUpdateSubscriptionTemplate,
  useDeleteSubscriptionTemplate,
} from "@/hooks/useSubscription"
import type { SubscriptionTemplate } from "@/api/subscription"
import { useTeams } from "@/hooks/useTeams"
import { useSports } from "@/hooks/useSports"
import { getLeagues } from "@/api/teams"
import { getSportDisplayName } from "@/lib/utils"

interface AssignmentsTabProps {
  templateId: number
  isTeamTemplate: boolean
}

interface EditingRule {
  id?: number
  sports: string[]
  leagues: string[]
}

function specificity(rule: SubscriptionTemplate): "League" | "Sport" | "Default" {
  if (rule.leagues && rule.leagues.length > 0) return "League"
  if (rule.sports && rule.sports.length > 0) return "Sport"
  return "Default"
}

export function AssignmentsTab({ templateId, isTeamTemplate }: AssignmentsTabProps) {
  if (isTeamTemplate) {
    return <TeamAssignments templateId={templateId} />
  }
  return <EventAssignments templateId={templateId} />
}

// ---------------------------------------------------------------------------
// Team templates: followed teams using this template (assignment lives on
// the Teams page)
// ---------------------------------------------------------------------------

function TeamAssignments({ templateId }: { templateId: number }) {
  const { data: teams, isLoading } = useTeams()
  const assigned = useMemo(
    () => (teams ?? []).filter((t) => t.template_id === templateId),
    [teams, templateId],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Teams Using This Template</CardTitle>
        <p className="text-sm text-muted-foreground">
          Team templates are assigned per followed team on the{" "}
          <Link to="/teams" className="text-primary hover:underline inline-flex items-center gap-0.5">
            Teams page <ExternalLink className="h-3 w-3" />
          </Link>
          . Teams without an explicit template use your default team template.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Spinner />
        ) : assigned.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            No teams are assigned to this template.
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {assigned.map((t) => (
              <span
                key={t.id}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-border bg-secondary/30 text-sm"
              >
                {t.team_logo_url && (
                  <img src={t.team_logo_url} alt="" className="h-4 w-4 object-contain" />
                )}
                {t.team_name}
                <Badge variant="outline" className="text-[10px] uppercase">
                  {t.primary_league}
                </Badge>
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Event templates: global assignment rules scoped to this template
// ---------------------------------------------------------------------------

function EventAssignments({ templateId }: { templateId: number }) {
  const [editing, setEditing] = useState<EditingRule | null>(null)

  const { data: subscription } = useSubscription()
  const subscribedLeagues = useMemo(
    () => subscription?.leagues ?? [],
    [subscription],
  )

  const { data: rulesData, isLoading } = useSubscriptionTemplates()
  const allRules = useMemo(() => rulesData?.templates ?? [], [rulesData])
  const myRules = useMemo(
    () => allRules.filter((r) => r.template_id === templateId),
    [allRules, templateId],
  )
  const otherRuleCount = allRules.length - myRules.length

  const { data: sportsData } = useSports()
  const sports = sportsData?.sports
  const sportsMap = useMemo(() => sports ?? {}, [sports])

  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
  })
  const leaguesList = leaguesData?.leagues
  const allLeagues = useMemo(() => leaguesList ?? [], [leaguesList])

  const subscribedSports = useMemo(
    () =>
      [...new Set(
        allLeagues.filter((l) => subscribedLeagues.includes(l.slug)).map((l) => l.sport),
      )].sort(),
    [allLeagues, subscribedLeagues],
  )

  const sportItems = useMemo(
    () =>
      subscribedSports.map((sport) => ({
        value: sport,
        label: getSportDisplayName(sport, sportsMap),
      })),
    [subscribedSports, sportsMap],
  )

  const leagueGroups: CheckboxListGroup[] = useMemo(() => {
    const grouped: Record<string, { slug: string; name: string }[]> = {}
    for (const slug of subscribedLeagues) {
      const league = allLeagues.find((l) => l.slug === slug)
      const sport = league?.sport || "other"
      if (!grouped[sport]) grouped[sport] = []
      grouped[sport].push({ slug, name: league?.name || slug })
    }
    return Object.keys(grouped)
      .sort()
      .map((sport) => ({
        key: sport,
        label: getSportDisplayName(sport, sportsMap),
        items: grouped[sport]
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((l) => ({ value: l.slug, label: l.name })),
      }))
  }, [subscribedLeagues, allLeagues, sportsMap])

  const createMutation = useCreateSubscriptionTemplate()
  const updateMutation = useUpdateSubscriptionTemplate()
  const deleteMutation = useDeleteSubscriptionTemplate()

  const handleSave = useCallback(() => {
    if (!editing) return
    const payload = {
      template_id: templateId,
      sports: editing.sports.length > 0 ? editing.sports : null,
      leagues: editing.leagues.length > 0 ? editing.leagues : null,
    }
    if (editing.id) {
      updateMutation.mutate(
        { assignmentId: editing.id, data: payload },
        { onSuccess: () => setEditing(null) },
      )
    } else {
      createMutation.mutate(payload, { onSuccess: () => setEditing(null) })
    }
  }, [editing, templateId, createMutation, updateMutation])

  const handleDelete = useCallback(
    (ruleId: number) => {
      if (confirm("Remove this assignment rule?")) {
        deleteMutation.mutate(ruleId)
      }
    },
    [deleteMutation],
  )

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-lg">Assignment Rules for This Template</CardTitle>
              <p className="text-sm text-muted-foreground">
                Events pick their template by the most specific matching rule: league &gt; sport
                &gt; default (no filters).
              </p>
            </div>
            {!editing && (
              <Button
                size="sm"
                className="shrink-0"
                onClick={() => setEditing({ sports: [], leagues: [] })}
              >
                <Plus className="h-4 w-4 mr-1" />
                Assign This Template
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <Spinner />
          ) : myRules.length === 0 && !editing ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              No assignment rules point at this template — events only use it if another
              surface (like a group) selects it. Add a rule to put it in the rotation.
            </div>
          ) : (
            myRules.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead>Applies To</TableHead>
                      <TableHead>Specificity</TableHead>
                      <TableHead className="text-right w-24">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {myRules.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {r.leagues?.map((l) => (
                              <Badge key={l} variant="secondary" className="text-xs">
                                {allLeagues.find((lg) => lg.slug === l)?.name || l}
                              </Badge>
                            ))}
                            {r.sports?.map((s) => (
                              <Badge key={s} variant="outline" className="text-xs">
                                {sportsMap[s] || s}
                              </Badge>
                            ))}
                            {!r.leagues?.length && !r.sports?.length && (
                              <span className="text-muted-foreground text-xs">
                                All events (default)
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              specificity(r) === "League"
                                ? "default"
                                : specificity(r) === "Sport"
                                  ? "secondary"
                                  : "outline"
                            }
                            className="text-xs"
                          >
                            {specificity(r)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0"
                              onClick={() =>
                                setEditing({
                                  id: r.id,
                                  sports: r.sports || [],
                                  leagues: r.leagues || [],
                                })
                              }
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(r.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )
          )}

          {editing && (
            <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
              <h4 className="font-medium text-sm">
                {editing.id ? "Edit Rule" : "New Rule"} — this template applies to:
              </h4>
              {subscribedSports.length > 1 && (
                <div className="space-y-2">
                  <Label>Sports (optional — leave empty for all)</Label>
                  <CheckboxListPicker
                    selected={editing.sports}
                    onChange={(sports) => setEditing((p) => (p ? { ...p, sports } : null))}
                    items={sportItems}
                    searchPlaceholder="Search sports..."
                    maxHeight="max-h-36"
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label>Leagues (optional — leave empty for all)</Label>
                <CheckboxListPicker
                  selected={editing.leagues}
                  onChange={(leagues) => setEditing((p) => (p ? { ...p, leagues } : null))}
                  groups={leagueGroups}
                  searchPlaceholder="Search leagues..."
                  maxHeight="max-h-48"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={() => setEditing(null)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={createMutation.isPending || updateMutation.isPending}
                >
                  {(createMutation.isPending || updateMutation.isPending) && (
                    <LoaderCircle className="h-4 w-4 animate-spin mr-1" />
                  )}
                  {editing.id ? "Update" : "Add"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex items-start gap-2 text-sm text-muted-foreground px-1">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <span>
          {otherRuleCount > 0
            ? `${otherRuleCount} other rule${otherRuleCount === 1 ? "" : "s"} assign${otherRuleCount === 1 ? "s" : ""} different templates. `
            : ""}
          To see every template's rules side by side (and resolve overlaps), use the{" "}
          <Link
            to="/epg/templates"
            className="text-primary hover:underline inline-flex items-center gap-0.5"
          >
            central Template Assignments manager <ExternalLink className="h-3 w-3" />
          </Link>
          .
        </span>
      </div>
    </div>
  )
}
