import { useState } from "react"
import { toast } from "sonner"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { StreamTimezoneSelector } from "@/components/StreamTimezoneSelector"
import { TeamPicker } from "@/components/TeamPicker"
import { useBulkUpdateGroups } from "@/hooks/useGroups"
import type { TeamFilterEntry } from "@/api/types"

interface BulkEditDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** ids of the stream sources the edit applies to */
  selectedIds: Set<number>
  /** league slugs for the team-filter picker */
  allLeagueSlugs: string[]
  /** called after a successful update (parent clears its selection) */
  onSuccess: () => void
}

/**
 * Bulk-edit modal for stream sources. Only checked fields are sent.
 *
 * The form body mounts fresh each time the dialog opens (Dialog unmounts its
 * children when closed), so form state resets without an explicit reset pass.
 */
export function BulkEditDialog({
  open,
  onOpenChange,
  selectedIds,
  allLeagueSlugs,
  onSuccess,
}: BulkEditDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <BulkEditForm
        onOpenChange={onOpenChange}
        selectedIds={selectedIds}
        allLeagueSlugs={allLeagueSlugs}
        onSuccess={onSuccess}
      />
    </Dialog>
  )
}

function BulkEditForm({
  onOpenChange,
  selectedIds,
  allLeagueSlugs,
  onSuccess,
}: Omit<BulkEditDialogProps, "open">) {
  const bulkUpdateMutation = useBulkUpdateGroups()

  // Checkboxes control which fields to update
  const [streamTimezoneEnabled, setStreamTimezoneEnabled] = useState(false)
  const [streamTimezone, setStreamTimezone] = useState<string | null>(null)
  const [clearStreamTimezone, setClearStreamTimezone] = useState(false)
  const [teamFilterEnabled, setTeamFilterEnabled] = useState(false)
  const [teamFilterAction, setTeamFilterAction] = useState<"set" | "clear">("set")
  const [teamFilterMode, setTeamFilterMode] = useState<"include" | "exclude">("include")
  const [teamFilterTeams, setTeamFilterTeams] = useState<TeamFilterEntry[]>([])
  const [bypassPlayoffs, setBypassPlayoffs] = useState(false)
  const [nameMatchEnabled, setNameMatchEnabled] = useState(false)
  const [nameMatch, setNameMatch] = useState(true)
  const [teamStreamsEnabled, setTeamStreamsEnabled] = useState(false)
  const [teamStreams, setTeamStreams] = useState(false)
  const [epgMatchEnabled, setEpgMatchEnabled] = useState(false)
  const [epgMatch, setEpgMatch] = useState(false)

  const anyFieldEnabled =
    streamTimezoneEnabled ||
    teamFilterEnabled ||
    nameMatchEnabled ||
    teamStreamsEnabled ||
    epgMatchEnabled

  const handleApply = async () => {
    // Build request with only enabled fields
    const request: Record<string, unknown> & { group_ids: number[] } = {
      group_ids: Array.from(selectedIds),
    }

    if (streamTimezoneEnabled) {
      if (clearStreamTimezone) {
        request.clear_stream_timezone = true
      } else if (streamTimezone) {
        request.stream_timezone = streamTimezone
      }
    }

    if (nameMatchEnabled) {
      request.name_match_enabled = nameMatch
    }

    if (teamStreamsEnabled) {
      request.team_streams_enabled = teamStreams
    }

    if (epgMatchEnabled) {
      request.epg_match_enabled = epgMatch
    }

    if (teamFilterEnabled) {
      if (teamFilterAction === "clear") {
        // Reset to global default
        request.clear_include_teams = true
        request.clear_exclude_teams = true
        request.clear_bypass_filter_for_playoffs = true
      } else {
        // Set custom filter
        request.team_filter_mode = teamFilterMode
        request.bypass_filter_for_playoffs = bypassPlayoffs
        if (teamFilterMode === "include") {
          request.include_teams = teamFilterTeams
          request.clear_exclude_teams = true
        } else {
          request.exclude_teams = teamFilterTeams
          request.clear_include_teams = true
        }
      }
    }

    try {
      const result = await bulkUpdateMutation.mutateAsync(request)
      if (result.total_failed > 0) {
        toast.warning(`Updated ${result.total_updated} groups, ${result.total_failed} failed`)
      } else {
        toast.success(`Updated ${result.total_updated} groups`)
      }
      onSuccess()
      onOpenChange(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update groups")
    }
  }

  return (
    <DialogContent onClose={() => onOpenChange(false)} className="max-w-3xl">
      <DialogHeader>
        <DialogTitle>Bulk Edit ({selectedIds.size} stream sources)</DialogTitle>
        <DialogDescription>
          Only checked fields will be updated. Use "Clear" to remove values.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4 py-4 px-1 max-h-[60vh] overflow-y-auto">
        {/* Stream Timezone */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={streamTimezoneEnabled}
              onCheckedChange={(checked) => setStreamTimezoneEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Stream Timezone</span>
          </label>
          {streamTimezoneEnabled && (
            <div className="space-y-2 pl-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox
                  checked={clearStreamTimezone}
                  onCheckedChange={(checked) => {
                    setClearStreamTimezone(!!checked)
                    if (checked) {
                      setStreamTimezone(null)
                    }
                  }}
                />
                <span className="text-sm font-normal">
                  Auto-detect from stream
                </span>
              </label>
              <StreamTimezoneSelector
                value={streamTimezone}
                onChange={setStreamTimezone}
                disabled={clearStreamTimezone}
              />
              <p className="text-xs text-muted-foreground">
                Timezone used in stream names for date matching
              </p>
            </div>
          )}
        </div>

        {/* Team Filter */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={teamFilterEnabled}
              onCheckedChange={(checked) => setTeamFilterEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Team Filter</span>
          </label>
          {teamFilterEnabled && (
            <div className="space-y-3 pl-6">
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="bulk-team-filter-action"
                    checked={teamFilterAction === "set"}
                    onChange={() => setTeamFilterAction("set")}
                    className="accent-primary"
                  />
                  <span className="text-sm">Set custom filter</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="bulk-team-filter-action"
                    checked={teamFilterAction === "clear"}
                    onChange={() => setTeamFilterAction("clear")}
                    className="accent-primary"
                  />
                  <span className="text-sm">Reset to global default</span>
                </label>
              </div>

              {teamFilterAction === "set" && (
                <div className="space-y-3">
                  <div className="flex items-center gap-4">
                    <Label>Mode:</Label>
                    <div className="flex gap-4">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="bulk-team-filter-mode"
                          checked={teamFilterMode === "include"}
                          onChange={() => setTeamFilterMode("include")}
                          className="accent-primary"
                        />
                        <span className="text-sm">Include only</span>
                      </label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="bulk-team-filter-mode"
                          checked={teamFilterMode === "exclude"}
                          onChange={() => setTeamFilterMode("exclude")}
                          className="accent-primary"
                        />
                        <span className="text-sm">Exclude</span>
                      </label>
                    </div>
                  </div>
                  <TeamPicker
                    leagues={allLeagueSlugs}
                    selectedTeams={teamFilterTeams}
                    onSelectionChange={setTeamFilterTeams}
                    placeholder="Search teams..."
                  />
                  <label className="flex items-center gap-2 cursor-pointer">
                    <Checkbox
                      checked={bypassPlayoffs}
                      onCheckedChange={(checked) => setBypassPlayoffs(!!checked)}
                    />
                    <span className="text-sm">Include all playoff games</span>
                  </label>
                </div>
              )}

              {teamFilterAction === "clear" && (
                <p className="text-xs text-muted-foreground">
                  Removes per-source team filter overrides. Stream sources will use the global default filter.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Stream Name Matching */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={nameMatchEnabled}
              onCheckedChange={(checked) => setNameMatchEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Stream name matching</span>
          </label>
          {nameMatchEnabled && (
            <div className="flex items-center gap-3 pl-6">
              <Switch checked={nameMatch} onCheckedChange={setNameMatch} />
              <span className="text-sm text-muted-foreground">
                {nameMatch ? "Enabled — match streams whose name identifies a specific event (e.g. \"Bills vs Dolphins\")" : "Disabled"}
              </span>
            </div>
          )}
        </div>

        {/* Team Stream Source */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={teamStreamsEnabled}
              onCheckedChange={(checked) => setTeamStreamsEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Team stream source</span>
          </label>
          {teamStreamsEnabled && (
            <div className="flex items-center gap-3 pl-6">
              <Switch checked={teamStreams} onCheckedChange={setTeamStreams} />
              <span className="text-sm text-muted-foreground">
                {teamStreams ? "Enabled — team-branded streams will match events where that team plays" : "Disabled"}
              </span>
            </div>
          )}
        </div>

        {/* EPG Program Matching */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={epgMatchEnabled}
              onCheckedChange={(checked) => setEpgMatchEnabled(!!checked)}
            />
            <span className="text-sm font-medium">EPG program matching</span>
          </label>
          {epgMatchEnabled && (
            <div className="flex items-center gap-3 pl-6">
              <Switch checked={epgMatch} onCheckedChange={setEpgMatch} />
              <span className="text-sm text-muted-foreground">
                {epgMatch ? "Enabled — match static-named linear channels to events via Dispatcharr's program guide (requires the global EPG matching switch)" : "Disabled"}
              </span>
            </div>
          )}
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          onClick={handleApply}
          disabled={bulkUpdateMutation.isPending || !anyFieldEnabled}
        >
          {bulkUpdateMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Apply to {selectedIds.size} groups
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
