import { useState } from "react"
import { toast } from "sonner"
import { LoaderCircle } from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { StreamTimezoneSelector } from "@/components/StreamTimezoneSelector"
import { TeamPicker } from "@/components/TeamPicker"
import { LeaguePicker } from "@/components/LeaguePicker"
import { SoccerModeSelector, type SoccerMode } from "@/components/SoccerModeSelector"
import { useBulkUpdateGroups } from "@/hooks/useGroups"
import { jsToPython } from "@/lib/regex-utils"
import { cn } from "@/lib/utils"
import type { BulkGroupUpdateRequest, SoccerFollowedTeam, TeamFilterEntry } from "@/api/types"

/**
 * Regex fields bulk edit can set (#551). One control per pattern: setting a
 * pattern also switches it on for every selected source, clearing it switches
 * it off — the backend applies that rule from the plain field + clear_* flag.
 */
const REGEX_FIELDS = [
  { key: "stream_include_regex", label: "Include streams matching", placeholder: "e.g., Gonzaga|Washington State|Eastern Washington" },
  { key: "stream_exclude_regex", label: "Exclude streams matching", placeholder: "e.g., \\(ES\\)|\\(ALT\\)|All.?Star" },
  { key: "custom_regex_teams", label: "Teams", placeholder: "(?<team1>[A-Z]{2,3})\\s*[@vs]+\\s*(?<team2>[A-Z]{2,3})" },
  { key: "custom_regex_date", label: "Date", placeholder: "(?<day>\\d{1,2})/(?<month>\\d{1,2})/(?<year>\\d{2,4})" },
  { key: "custom_regex_month", label: "Month", placeholder: "(?<month>\\w+)" },
  { key: "custom_regex_day", label: "Day", placeholder: "(?<day>\\d{1,2})" },
  { key: "custom_regex_time", label: "Time", placeholder: "(?<time>\\d{1,2}:\\d{2}\\s*(?:AM|PM)?)" },
  { key: "custom_regex_league", label: "League", placeholder: "(?<league>NHL|NBA|NFL|MLB)" },
  { key: "custom_regex_fighters", label: "Fighters", placeholder: "(?<fighter1>\\w+)\\s+vs\\.?\\s+(?<fighter2>\\w+)" },
  { key: "custom_regex_event_name", label: "Event name", placeholder: "(?<event_name>UFC\\s*\\d+|Bellator\\s*\\d+)" },
] as const

type RegexKey = (typeof REGEX_FIELDS)[number]["key"]
type RegexAction = "set" | "clear"
type RegexEdit = { action: RegexAction; pattern: string }

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

  // Subscription override (#551): set a shared league list, or reset to global.
  const [subscriptionEnabled, setSubscriptionEnabled] = useState(false)
  const [subscriptionAction, setSubscriptionAction] = useState<"set" | "clear">("set")
  const [overrideNonSoccerLeagues, setOverrideNonSoccerLeagues] = useState<string[]>([])
  const [overrideSoccerLeagues, setOverrideSoccerLeagues] = useState<string[]>([])
  const [overrideSoccerMode, setOverrideSoccerMode] = useState<SoccerMode | null>(null)
  const [overrideFollowedTeams, setOverrideFollowedTeams] = useState<SoccerFollowedTeam[]>([])

  // Stream filters + custom regex (#551): each field is opt-in, then set or clear.
  const [skipBuiltinEnabled, setSkipBuiltinEnabled] = useState(false)
  const [skipBuiltin, setSkipBuiltin] = useState(false)
  const [regexEdits, setRegexEdits] = useState<Partial<Record<RegexKey, RegexEdit>>>({})

  const setRegexEdit = (key: RegexKey, edit: RegexEdit | null) =>
    setRegexEdits((prev) => {
      const next = { ...prev }
      if (edit) next[key] = edit
      else delete next[key]
      return next
    })

  const anyFieldEnabled =
    streamTimezoneEnabled ||
    teamFilterEnabled ||
    nameMatchEnabled ||
    teamStreamsEnabled ||
    epgMatchEnabled ||
    subscriptionEnabled ||
    skipBuiltinEnabled ||
    Object.keys(regexEdits).length > 0

  const handleApply = async () => {
    // Build request with only enabled fields
    const request: BulkGroupUpdateRequest = {
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

    if (subscriptionEnabled) {
      if (subscriptionAction === "clear") {
        request.clear_subscription_leagues = true
        request.clear_subscription_soccer_mode = true
        request.clear_subscription_soccer_followed_teams = true
      } else {
        request.subscription_leagues = [...overrideNonSoccerLeagues, ...overrideSoccerLeagues]
        request.subscription_soccer_mode = overrideSoccerMode
        request.subscription_soccer_followed_teams =
          overrideFollowedTeams.length > 0 ? overrideFollowedTeams : null
      }
    }

    if (skipBuiltinEnabled) {
      request.skip_builtin_filter = skipBuiltin
    }

    for (const [key, edit] of Object.entries(regexEdits) as [RegexKey, RegexEdit][]) {
      if (edit.action === "clear") {
        request[`clear_${key}`] = true
      } else if (edit.pattern.trim()) {
        request[key] = jsToPython(edit.pattern.trim())
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
                    <span className="text-sm">Include all playoff &amp; All-Star games</span>
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

        {/* Subscription Override (#551) */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={subscriptionEnabled}
              onCheckedChange={(checked) => setSubscriptionEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Subscription override (leagues)</span>
          </label>
          {subscriptionEnabled && (
            <div className="space-y-3 pl-6">
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="bulk-subscription-action"
                    checked={subscriptionAction === "set"}
                    onChange={() => setSubscriptionAction("set")}
                    className="accent-primary"
                  />
                  <span className="text-sm">Set custom leagues</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="bulk-subscription-action"
                    checked={subscriptionAction === "clear"}
                    onChange={() => setSubscriptionAction("clear")}
                    className="accent-primary"
                  />
                  <span className="text-sm">Use global subscription</span>
                </label>
              </div>
              {subscriptionAction === "set" ? (
                <>
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Non-Soccer Sports</Label>
                    <LeaguePicker
                      selectedLeagues={overrideNonSoccerLeagues}
                      onSelectionChange={setOverrideNonSoccerLeagues}
                      excludeSport="soccer"
                      maxHeight="max-h-48"
                      showSearch={true}
                      showSelectedBadges={true}
                      maxBadges={8}
                    />
                  </div>
                  <div className="border-t" />
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Soccer Leagues</Label>
                    <SoccerModeSelector
                      mode={overrideSoccerMode}
                      onModeChange={setOverrideSoccerMode}
                      selectedLeagues={overrideSoccerLeagues}
                      onLeaguesChange={setOverrideSoccerLeagues}
                      followedTeams={overrideFollowedTeams}
                      onFollowedTeamsChange={setOverrideFollowedTeams}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Replaces each selected source's league override with this list.
                  </p>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Removes per-source league overrides. Sources will match against the global
                  subscription (set on the Subscriptions page).
                </p>
              )}
            </div>
          )}
        </div>

        {/* Stream filters + custom regex (#551) */}
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={skipBuiltinEnabled}
              onCheckedChange={(checked) => setSkipBuiltinEnabled(!!checked)}
            />
            <span className="text-sm font-medium">Skip built-in filter</span>
          </label>
          {skipBuiltinEnabled && (
            <div className="flex items-center gap-3 pl-6">
              <Switch checked={skipBuiltin} onCheckedChange={setSkipBuiltin} />
              <span className="text-sm text-muted-foreground">
                {skipBuiltin
                  ? "Enabled — rely on your include/exclude regex instead of the built-in event filter"
                  : "Disabled — built-in event filter runs first"}
              </span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">Stream filters &amp; custom regex</p>
          <p className="text-xs text-muted-foreground">
            Check a field to change it on every selected source. Setting a pattern also switches
            it on; clearing switches it off. Unchecked fields are left as they are.
          </p>
          <div className="space-y-2 pl-1">
            {REGEX_FIELDS.map(({ key, label, placeholder }) => {
              const edit = regexEdits[key]
              return (
                <div key={key} className="space-y-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <Checkbox
                      checked={!!edit}
                      onCheckedChange={(checked) =>
                        setRegexEdit(key, checked ? { action: "set", pattern: "" } : null)
                      }
                    />
                    <span className="text-sm">{label}</span>
                  </label>
                  {edit && (
                    <div className="flex items-center gap-3 pl-6">
                      <label className="flex items-center gap-1 cursor-pointer text-xs">
                        <input
                          type="radio"
                          name={`bulk-regex-${key}`}
                          checked={edit.action === "set"}
                          onChange={() => setRegexEdit(key, { ...edit, action: "set" })}
                          className="accent-primary"
                        />
                        Set
                      </label>
                      <label className="flex items-center gap-1 cursor-pointer text-xs">
                        <input
                          type="radio"
                          name={`bulk-regex-${key}`}
                          checked={edit.action === "clear"}
                          onChange={() => setRegexEdit(key, { ...edit, action: "clear" })}
                          className="accent-primary"
                        />
                        Clear
                      </label>
                      <Input
                        value={edit.pattern}
                        onChange={(e) => setRegexEdit(key, { ...edit, pattern: e.target.value })}
                        placeholder={placeholder}
                        disabled={edit.action === "clear"}
                        className={cn("font-mono text-sm", edit.action === "clear" && "opacity-50")}
                      />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
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
                {epgMatch ? "Enabled — match static-named linear channels to events via Dispatcharr's program guide" : "Disabled"}
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
          {bulkUpdateMutation.isPending && <LoaderCircle className="h-4 w-4 mr-2 animate-spin" />}
          Apply to {selectedIds.size} groups
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
