/**
 * TemplateAssignmentManager — manage global subscription template assignments.
 *
 * Allows assigning different templates based on sport/league filters:
 * - leagues match (most specific) → sports match → default (fallback)
 *
 * Rendered as a static page section (EPG → Template Assignments). Was formerly a
 * Dialog (TemplateAssignmentModal); promoted to a page in the v2.7.0 IA overhaul.
 */

import { useState, useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
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
  useSubscriptionTemplates,
  useCreateSubscriptionTemplate,
  useUpdateSubscriptionTemplate,
  useDeleteSubscriptionTemplate,
} from "@/hooks/useSubscription"
import type { SubscriptionTemplate } from "@/api/subscription"
import { useTemplates } from "@/hooks/useTemplates"
import { useSports } from "@/hooks/useSports"
import { getLeagues } from "@/api/teams"
import { getSportDisplayName } from "@/lib/utils"
import { Loader2, Plus, Pencil, Trash2 } from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TemplateAssignmentManagerProps {
  /** Subscribed leagues for filtering sport/league pickers */
  subscribedLeagues: string[]
}

interface EditingAssignment {
  id?: number // undefined for new, number for edit
  template_id: number | null
  sports: string[]
  leagues: string[]
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TemplateAssignmentManager({
  subscribedLeagues,
}: TemplateAssignmentManagerProps) {
  // Form state for add/edit
  const [editing, setEditing] = useState<EditingAssignment | null>(null)

  // Fetch current subscription templates
  const {
    data: templatesData,
    isLoading,
    error,
  } = useSubscriptionTemplates()
  const assignments = templatesData?.templates || []

  // Fetch event templates for dropdown
  const { data: templates } = useTemplates()
  const eventTemplates = templates?.filter((t) => t.template_type === "event") || []

  // Fetch sports for dropdown
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports || {}

  // Fetch leagues for display
  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
  })
  const allLeagues = leaguesData?.leagues || []

  // Get unique sports from subscribed leagues (sorted)
  const subscribedSports = useMemo(() =>
    [...new Set(
      allLeagues
        .filter((l) => subscribedLeagues.includes(l.slug))
        .map((l) => l.sport)
    )].sort(),
    [allLeagues, subscribedLeagues]
  )

  // Build sport items for CheckboxListPicker (flat mode)
  const sportItems = useMemo(() =>
    subscribedSports.map((sport) => ({
      value: sport,
      label: getSportDisplayName(sport, sportsMap),
    })),
    [subscribedSports, sportsMap]
  )

  // Build league groups for CheckboxListPicker (grouped mode)
  const leagueGroups: CheckboxListGroup[] = useMemo(() => {
    const grouped: Record<string, { slug: string; name: string; sport: string }[]> = {}
    for (const slug of subscribedLeagues) {
      const league = allLeagues.find((l) => l.slug === slug)
      const sport = league?.sport || "other"
      if (!grouped[sport]) grouped[sport] = []
      grouped[sport].push({ slug, name: league?.name || slug, sport })
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

  // Mutations
  const createMutation = useCreateSubscriptionTemplate()
  const updateMutation = useUpdateSubscriptionTemplate()
  const deleteMutation = useDeleteSubscriptionTemplate()

  const handleAdd = useCallback(() => {
    setEditing({
      template_id: null,
      sports: [],
      leagues: [],
    })
  }, [])

  const handleEdit = useCallback((assignment: SubscriptionTemplate) => {
    setEditing({
      id: assignment.id,
      template_id: assignment.template_id,
      sports: assignment.sports || [],
      leagues: assignment.leagues || [],
    })
  }, [])

  const handleDelete = useCallback(
    (assignmentId: number) => {
      if (confirm("Delete this template assignment?")) {
        deleteMutation.mutate(assignmentId)
      }
    },
    [deleteMutation]
  )

  const handleSave = useCallback(() => {
    if (!editing || !editing.template_id) return

    const sports = editing.sports.length > 0 ? editing.sports : null
    const leagues = editing.leagues.length > 0 ? editing.leagues : null

    if (editing.id) {
      updateMutation.mutate({
        assignmentId: editing.id,
        data: {
          template_id: editing.template_id,
          sports: sports,
          leagues: leagues,
        },
      }, { onSuccess: () => setEditing(null) })
    } else {
      createMutation.mutate({
        template_id: editing.template_id,
        sports: sports,
        leagues: leagues,
      }, { onSuccess: () => setEditing(null) })
    }
  }, [editing, createMutation, updateMutation])

  const handleCancel = useCallback(() => {
    setEditing(null)
  }, [])

  // --- Selection change handlers for CheckboxListPicker ---
  const handleSportsChange = useCallback((sports: string[]) => {
    setEditing((prev) => prev ? { ...prev, sports } : null)
  }, [])

  const handleLeaguesChange = useCallback((leagues: string[]) => {
    setEditing((prev) => prev ? { ...prev, leagues } : null)
  }, [])

  const getSpecificityLabel = (assignment: SubscriptionTemplate) => {
    if (assignment.leagues && assignment.leagues.length > 0) {
      return "League"
    }
    if (assignment.sports && assignment.sports.length > 0) {
      return "Sport"
    }
    return "Default"
  }

  return (
    <div className="space-y-4">
      {/* Section header + add action — mirrors the Templates page header (title
          left, standard add button right) */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Template Assignments</h2>
          <p className="text-sm text-muted-foreground">
            Assign event templates by sport or league. More specific matches win: league &gt; sport &gt; default.
          </p>
        </div>
        {!editing && (
          <Button size="sm" onClick={handleAdd} className="shrink-0">
            <Plus className="h-4 w-4 mr-1" />
            Add Template Assignment
          </Button>
        )}
      </div>

      {/* Current assignments */}
      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <div className="text-sm text-destructive py-4">
          Failed to load template assignments.
        </div>
      )}

      {!isLoading && !error && (
        <>
          {/* Assignments table */}
          {assignments.length > 0 ? (
            <div className="border rounded-lg overflow-hidden">
              <Table>
                <TableHeader className="bg-muted/50">
                  <TableRow>
                    <TableHead>Template</TableHead>
                    <TableHead>Filter</TableHead>
                    <TableHead>Specificity</TableHead>
                    <TableHead className="text-right w-24">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assignments.map((a: SubscriptionTemplate) => (
                    <TableRow key={a.id}>
                      <TableCell>{a.template_name || `Template ${a.template_id}`}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {a.leagues?.map((l: string) => (
                            <Badge key={l} variant="secondary" className="text-xs">
                              {allLeagues.find((lg) => lg.slug === l)?.name || l}
                            </Badge>
                          ))}
                          {a.sports?.map((s: string) => (
                            <Badge key={s} variant="outline" className="text-xs">
                              {sportsMap[s] || s}
                            </Badge>
                          ))}
                          {!a.leagues?.length && !a.sports?.length && (
                            <span className="text-muted-foreground text-xs">All events</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            getSpecificityLabel(a) === "League"
                              ? "default"
                              : getSpecificityLabel(a) === "Sport"
                              ? "secondary"
                              : "outline"
                          }
                          className="text-xs"
                        >
                          {getSpecificityLabel(a)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            onClick={() => handleEdit(a)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                            onClick={() => handleDelete(a.id)}
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
          ) : (
            <div className="text-center py-8 text-muted-foreground text-sm">
              No template assignments yet. Add one to get started.
            </div>
          )}

          {/* Add/Edit form */}
          {editing && (
            <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
              <h4 className="font-medium text-sm">
                {editing.id ? "Edit Assignment" : "New Assignment"}
              </h4>

              {/* Template select */}
              <div className="space-y-2">
                <Label>Template</Label>
                <Select
                  value={editing.template_id?.toString() || ""}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      template_id: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                >
                  <option value="">Select template...</option>
                  {eventTemplates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </Select>
              </div>

              {/* Sports filter */}
              {subscribedSports.length > 1 && (
                <div className="space-y-2">
                  <Label>Sports (optional — leave empty for all)</Label>
                  <CheckboxListPicker
                    selected={editing.sports}
                    onChange={handleSportsChange}
                    items={sportItems}
                    searchPlaceholder="Search sports..."
                    maxHeight="max-h-36"
                  />
                </div>
              )}

              {/* Leagues filter */}
              <div className="space-y-2">
                <Label>Leagues (optional — leave empty for all)</Label>
                <CheckboxListPicker
                  selected={editing.leagues}
                  onChange={handleLeaguesChange}
                  groups={leagueGroups}
                  searchPlaceholder="Search leagues..."
                  maxHeight="max-h-48"
                />
              </div>

              {/* Form actions */}
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={handleCancel}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={!editing.template_id || createMutation.isPending || updateMutation.isPending}
                >
                  {createMutation.isPending || updateMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1" />
                  ) : null}
                  {editing.id ? "Update" : "Add"}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
