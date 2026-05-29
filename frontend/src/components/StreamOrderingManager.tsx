import { useState, useEffect, useMemo, useRef } from "react"
import { useQuery, useQueries } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  Plus,
  Trash2,
  Loader2,
  Save,
  AlertCircle,
  ChevronDown,
  Info,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import { cn } from "@/lib/utils"
import {
  useStreamOrderingSettings,
  useUpdateStreamOrderingSettings,
  useTeamFilterSettings,
} from "@/hooks/useSettings"
import { useGroups } from "@/hooks/useGroups"
import { getLeagueTeams, getTeamPickerLeagues } from "@/api/teams"
import type { CachedTeam } from "@/api/teams"

function TeamMultiSelect({
  selected,
  onChange,
  noSelectionLabel = "No teams selected (inactive)",
}: {
  selected: string[]
  onChange: (ids: string[]) => void
  noSelectionLabel?: string
}) {
  const { data: teamFilter } = useTeamFilterSettings()
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  const { data: leaguesData, isLoading: leaguesLoading } = useQuery({
    queryKey: ["teamPickerLeagues"],
    queryFn: getTeamPickerLeagues,
    staleTime: 5 * 60 * 1000,
  })

  // Only configured leagues — unconfigured leagues have no user-relevant teams
  const allLeagueSlugs = useMemo(
    () => leaguesData?.leagues.filter(l => l.is_configured).map(l => l.slug) ?? [],
    [leaguesData]
  )

  // Fetch teams for every configured league in parallel
  const teamQueries = useQueries({
    queries: allLeagueSlugs.map(slug => ({
      queryKey: ["leagueTeams", slug],
      queryFn: (): Promise<CachedTeam[]> => getLeagueTeams(slug),
      staleTime: 5 * 60 * 1000,
    })),
  })

  const isLoading = leaguesLoading || teamQueries.some(q => q.isLoading)

  // Build league groups; item value is "provider:provider_team_id"
  const leagueGroups = useMemo(() => {
    if (!leaguesData) return []
    const configured = leaguesData.leagues.filter(l => l.is_configured)
    return configured
      .map((league, i) => ({
        slug: league.slug,
        name: league.name,
        teams: (teamQueries[i]?.data ?? [])
          .map((ct: CachedTeam) => ({
            id: `${ct.provider}:${ct.league}:${ct.provider_team_id}`,
            name: ct.team_name,
            abbrev: ct.team_abbrev,
            logo: ct.logo_url,
          }))
          .sort((a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name)),
      }))
      .filter(g => g.teams.length > 0)
  }, [leaguesData, teamQueries])

  // "Default": team filter include list; league-qualified to avoid cross-sport provider ID collisions
  const defaultIds = useMemo(() => {
    if (teamFilter?.mode !== "include" || !teamFilter.include_teams?.length) return []
    return teamFilter.include_teams.map(te => `${te.provider}:${te.league}:${te.team_id}`)
  }, [teamFilter])

  const defaultIdSet = useMemo(() => new Set(defaultIds), [defaultIds])

  const filteredGroups = useMemo(() => {
    if (!search.trim()) return leagueGroups
    const q = search.toLowerCase()
    return leagueGroups
      .map(g => ({
        ...g,
        teams: g.teams.filter(
          t => t.name.toLowerCase().includes(q) || (t.abbrev?.toLowerCase().includes(q) ?? false)
        ),
      }))
      .filter(g => g.teams.length > 0)
  }, [leagueGroups, search])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const selectedSet = useMemo(() => new Set(selected), [selected])
  const [expandedLeagues, setExpandedLeagues] = useState<Set<string>>(new Set())
  const isSearching = search.trim().length >= 3
  const isLeagueExpanded = (slug: string) => isSearching || expandedLeagues.has(slug)

  const toggleLeague = (slug: string) => {
    setExpandedLeagues(prev => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  const toggle = (id: string) => {
    const next = new Set(selectedSet)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(Array.from(next))
  }

  const triggerLabel = selected.length === 0
    ? noSelectionLabel
    : `${selected.length} team${selected.length === 1 ? "" : "s"} selected`

  return (
    <div ref={containerRef} className="relative flex-1">
      <button
        type="button"
        onClick={() => setIsOpen(o => !o)}
        className={cn(
          "flex items-center justify-between w-full h-9 px-3 text-sm",
          "bg-background border border-input rounded-md cursor-pointer",
          "hover:border-ring focus:outline-none focus:ring-1 focus:ring-ring",
          selected.length === 0 && "text-muted-foreground"
        )}
      >
        <span className="truncate">{triggerLabel}</span>
        <ChevronDown className={cn("h-4 w-4 ml-1 shrink-0 opacity-50 transition-transform", isOpen && "rotate-180")} />
      </button>

      {isOpen && (
        <div className="absolute z-50 mt-1 w-full min-w-[240px] bg-card border border-border rounded-md shadow-lg">
          <div className="p-2 border-b">
            <Input
              placeholder="Search teams..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-7 text-sm"
              autoFocus
            />
          </div>

          <div className="max-h-64 overflow-y-auto">
            {isLoading ? (
              <div className="px-3 py-2 text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading teams...
              </div>
            ) : filteredGroups.length === 0 ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">No teams found</div>
            ) : (
              filteredGroups.map(group => {
                const teamsToShow = isLeagueExpanded(group.slug)
                  ? group.teams
                  : group.teams.filter(t => selectedSet.has(t.id) || defaultIdSet.has(t.id))
                if (teamsToShow.length === 0) return null
                return (
                  <div key={group.slug}>
                    <button
                      type="button"
                      onClick={() => toggleLeague(group.slug)}
                      className="w-full flex items-center justify-between px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground bg-muted/40 sticky top-0 hover:bg-muted/60"
                    >
                      <span>{group.name}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="normal-case opacity-60">{group.teams.length}</span>
                        <ChevronDown className={cn("h-3 w-3 transition-transform", isLeagueExpanded(group.slug) && "rotate-180")} />
                      </div>
                    </button>
                    {teamsToShow.map(team => {
                      const checked = selectedSet.has(team.id)
                      return (
                        <label
                          key={team.id}
                          className={cn(
                            "flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-accent text-sm",
                            checked && "bg-primary/10"
                          )}
                        >
                          <Checkbox checked={checked} onCheckedChange={() => toggle(team.id)} />
                          {team.logo && (
                            <img
                              src={team.logo}
                              alt=""
                              className="h-4 w-4 object-contain shrink-0"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none" }}
                            />
                          )}
                          <span className="truncate">
                            {team.name}
                            {team.abbrev && (
                              <span className="text-muted-foreground ml-1 text-xs">({team.abbrev})</span>
                            )}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                )
              })
            )}
          </div>

          <div className="p-1.5 border-t flex gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs flex-1"
              onClick={() => onChange(defaultIds)}
              disabled={defaultIds.length === 0}
            >
              Default
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs flex-1"
              onClick={() => onChange([])}
            >
              Clear
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

const RULE_TYPES = [
  { value: "m3u", label: "M3U Account", description: "Match streams by M3U account name" },
  { value: "group", label: "Event Group", description: "Match streams by event group name" },
  { value: "regex", label: "Regex Pattern", description: "Match streams by regex against stream name" },
  { value: "stream_type", label: "Stream Type", description: "Match by stream type: event stream or team stream" },
  { value: "team_feed", label: "Home/Away Feed", description: "Match streams that appear to be a team's own broadcast (home or away feed) for any enabled team" },
] as const

const STREAM_TYPE_OPTIONS = [
  { value: "event", label: "Event stream" },
  { value: "team", label: "Team stream" },
]

function parseStreamTypeValue(value: string) {
  const pipeIdx = value.indexOf("|")
  if (pipeIdx === -1) return { streamType: value, teamIds: [] as string[] }
  return {
    streamType: value.slice(0, pipeIdx),
    teamIds: value.slice(pipeIdx + 1).split(",").filter(Boolean),
  }
}

const NO_VALUE_TYPES = new Set(["team_feed", "not_team_feed", "catch_all"])

interface RuleFormData {
  // Stable client-side id so rows keep their identity across re-sorts.
  // Without this, keying by array index causes focus to follow DOM position
  // instead of the rule, breaking double-digit priority entry (#198).
  _id: number
  type: "m3u" | "group" | "regex" | "stream_type" | "team_feed" | "not_team_feed" | "catch_all"
  value: string
  priority: number
}

const TEAM_FEED_FAMILY = new Set<RuleFormData["type"]>(["team_feed", "not_team_feed"])

function PriorityInput({
  value,
  onCommit,
}: {
  value: number
  onCommit: (next: number) => void
}) {
  // Local string state so the input doesn't re-sort the row mid-keystroke.
  // Commits on blur or Enter; reverts to last valid value if input is invalid.
  const [text, setText] = useState(String(value))

  useEffect(() => {
    setText(String(value))
  }, [value])

  const commit = () => {
    const parsed = parseInt(text, 10)
    if (!isNaN(parsed) && parsed >= 1 && parsed <= 99) {
      if (parsed !== value) onCommit(parsed)
      else setText(String(value))
    } else {
      setText(String(value))
    }
  }

  return (
    <Input
      type="number"
      min={1}
      max={99}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          e.currentTarget.blur()
        }
      }}
      className="text-center"
    />
  )
}

function RuleRow({
  rule,
  index,
  onUpdate,
  onDelete,
  m3uAccounts,
  groupNames,
}: {
  rule: RuleFormData
  index: number
  onUpdate: (index: number, rule: RuleFormData) => void
  onDelete: (index: number) => void
  m3uAccounts: string[]
  groupNames: string[]
}) {
  const isCatchAll = rule.type === "catch_all"

  const handleTypeChange = (newType: RuleFormData["type"]) => {
    if (newType === rule.type) return
    // Preserve team selection when staying within the team_feed family
    const value = TEAM_FEED_FAMILY.has(rule.type) && TEAM_FEED_FAMILY.has(newType)
      ? rule.value
      : ""
    onUpdate(index, { ...rule, type: newType, value })
  }

  if (isCatchAll) {
    return (
      <div className="flex items-center gap-2 p-2 rounded-md border bg-muted/30">
        <div className="flex-1 grid grid-cols-12 gap-2 items-center">
          <div className="col-span-2">
            <span className="text-sm font-medium px-3">Everything Else</span>
          </div>
          <div className="col-span-7">
            <span className="text-sm text-muted-foreground italic px-1">All unmatched streams (Not captured by other rules on this page)</span>
          </div>
          <div className="col-span-2">
            <PriorityInput
              value={rule.priority}
              onCommit={(priority) => onUpdate(index, { ...rule, priority })}
            />
          </div>
          <div className="col-span-1" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 p-2 rounded-md border bg-card">
      <div className="flex-1 grid grid-cols-12 gap-2 items-center">
        <div className="col-span-2">
          <Select
            value={TEAM_FEED_FAMILY.has(rule.type) ? "team_feed" : rule.type}
            onChange={(e) => handleTypeChange(e.target.value as RuleFormData["type"])}
          >
            {RULE_TYPES.map(type => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </Select>
        </div>

        <div className="col-span-7">
          {rule.type === "m3u" ? (
            <Select
              value={rule.value}
              onChange={(e) => onUpdate(index, { ...rule, value: e.target.value })}
            >
              <option value="">Select M3U account...</option>
              {m3uAccounts.map(account => (
                <option key={account} value={account}>{account}</option>
              ))}
            </Select>
          ) : rule.type === "group" ? (
            <Select
              value={rule.value}
              onChange={(e) => onUpdate(index, { ...rule, value: e.target.value })}
            >
              <option value="">Select event group...</option>
              {groupNames.map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </Select>
          ) : rule.type === "stream_type" ? (() => {
            const { streamType, teamIds } = parseStreamTypeValue(rule.value)
            const typeSelect = (
              <Select
                value={streamType}
                onChange={(e) => {
                  const next = e.target.value
                  // Switching to event: drop team portion; to team: keep existing team ids
                  if (next === "event") {
                    onUpdate(index, { ...rule, value: "event" })
                  } else {
                    onUpdate(index, { ...rule, value: teamIds.length ? `team|${teamIds.join(",")}` : "team" })
                  }
                }}
              >
                <option value="">Select stream type...</option>
                {STREAM_TYPE_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            )
            if (streamType !== "team") return typeSelect
            return (
              <div className="flex gap-2">
                <div className="w-1/2">{typeSelect}</div>
                <div className="w-1/2">
                  <TeamMultiSelect
                    selected={teamIds}
                    onChange={(ids) => onUpdate(index, { ...rule, value: ids.length ? `team|${ids.join(",")}` : "team" })}
                    noSelectionLabel="All team streams"
                  />
                </div>
              </div>
            )
          })() : TEAM_FEED_FAMILY.has(rule.type) ? (
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 cursor-pointer select-none shrink-0">
                <Checkbox
                  checked={rule.type === "not_team_feed"}
                  onCheckedChange={(checked) =>
                    onUpdate(index, { ...rule, type: checked ? "not_team_feed" : "team_feed" })
                  }
                />
                <span className="text-sm text-muted-foreground">Invert</span>
                <RichTooltip
                  content="When checked, matches streams that carry home/away/feed markers but are NOT your selected teams' own broadcast — useful for pushing other teams' feeds to the back."
                  side="top"
                >
                  <Info className="h-3 w-3 text-muted-foreground/50 cursor-help shrink-0" />
                </RichTooltip>
              </label>
              <TeamMultiSelect
                selected={rule.value ? rule.value.split(",") : []}
                onChange={(ids) => onUpdate(index, { ...rule, value: ids.join(",") })}
              />
            </div>
          ) : (
            <Input
              value={rule.value}
              onChange={(e) => onUpdate(index, { ...rule, value: e.target.value })}
              placeholder="Regex pattern (e.g., .*HD.*)"
            />
          )}
        </div>

        <div className="col-span-2">
          <PriorityInput
            value={rule.priority}
            onCommit={(priority) => onUpdate(index, { ...rule, priority })}
          />
        </div>

        <div className="col-span-1 flex justify-end">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDelete(index)}
            className="h-8 w-8 text-destructive hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}

export function StreamOrderingManager() {
  const { data: settings, isLoading, error } = useStreamOrderingSettings()
  const updateSettings = useUpdateStreamOrderingSettings()
  const { data: groupsData } = useGroups(true) // Include disabled groups

  const [rules, setRules] = useState<RuleFormData[]>([])
  const [hasChanges, setHasChanges] = useState(false)
  const nextIdRef = useRef(0)
  const allocateId = () => ++nextIdRef.current

  // Extract unique M3U account names and group names from groups
  const { m3uAccounts, groupNames } = useMemo(() => {
    if (!groupsData?.groups) {
      return { m3uAccounts: [], groupNames: [] }
    }

    const accounts = new Set<string>()
    const names = new Set<string>()

    for (const group of groupsData.groups) {
      if (group.m3u_account_name) {
        accounts.add(group.m3u_account_name)
      }
      if (group.name) {
        names.add(group.name)
      }
    }

    return {
      m3uAccounts: Array.from(accounts).sort(),
      groupNames: Array.from(names).sort(),
    }
  }, [groupsData])

  // Initialize rules from settings; auto-inject catch_all if absent
  useEffect(() => {
    if (settings?.rules) {
      const loaded: RuleFormData[] = settings.rules.map(r => ({
        _id: allocateId(),
        type: r.type,
        value: r.value,
        priority: r.priority,
      }))
      if (!loaded.some(r => r.type === "catch_all")) {
        loaded.push({ _id: allocateId(), type: "catch_all", value: "", priority: 99 })
      }
      setRules(loaded)
      setHasChanges(false)
    }
  }, [settings])

  const handleAddRule = () => {
    // Find next available priority (skip 99 if catch_all is using it)
    const usedPriorities = new Set(rules.map(r => r.priority))
    let nextPriority = 1
    while (usedPriorities.has(nextPriority) && nextPriority < 99) {
      nextPriority++
    }

    setRules([
      ...rules,
      { _id: allocateId(), type: "m3u", value: "", priority: nextPriority },
    ])
    setHasChanges(true)
  }

  const handleUpdateRule = (index: number, updatedRule: RuleFormData) => {
    const newRules = [...rules]
    newRules[index] = updatedRule
    setRules(newRules)
    setHasChanges(true)
  }

  const handleDeleteRule = (index: number) => {
    if (rules[index].type === "catch_all") return
    setRules(rules.filter((_, i) => i !== index))
    setHasChanges(true)
  }

  const handleSave = async () => {
    // Validate rules — no-value types (team_feed, not_team_feed, catch_all) don't require a value
    const invalidRules = rules.filter(r => !NO_VALUE_TYPES.has(r.type) && !r.value.trim())

    if (invalidRules.length > 0) {
      toast.error("Please fill in all rule values or remove empty rules")
      return
    }

    try {
      await updateSettings.mutateAsync({
        rules: rules.map((r: RuleFormData) => ({
          type: r.type,
          value: r.value.trim(),
          priority: r.priority,
        })),
      })
      toast.success("Stream ordering rules saved")
      setHasChanges(false)
    } catch (err) {
      toast.error("Failed to save stream ordering rules")
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-destructive">
          <AlertCircle className="h-5 w-5" />
          <span>Failed to load stream ordering settings</span>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Stream Ordering</CardTitle>
        <CardDescription>
          Prioritize streams within channels based on M3U account, event group, or custom patterns.
          Lower priority numbers appear first. Streams not matching any rule are sorted to the end.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {rules.length > 0 && (
          <div className="space-y-2">
            {/* Header row */}
            <div className="grid grid-cols-12 gap-2 px-2 text-xs font-medium text-muted-foreground">
              <div className="col-span-2">Type</div>
              <div className="col-span-7">Value</div>
              <div className="col-span-2 text-center">Priority</div>
              <div className="col-span-1"></div>
            </div>

            {/* Rules */}
            {rules
              .slice()
              .sort((a, b) => a.priority - b.priority)
              .map((rule) => (
                <RuleRow
                  key={rule._id}
                  rule={rule}
                  index={rules.indexOf(rule)}
                  onUpdate={handleUpdateRule}
                  onDelete={handleDeleteRule}
                  m3uAccounts={m3uAccounts}
                  groupNames={groupNames}
                />
              ))}
          </div>
        )}

        {rules.length === 0 && (
          <div className="text-center py-6 text-muted-foreground">
            <p className="text-sm">No ordering rules configured.</p>
            <p className="text-xs mt-1">Streams will be ordered by addition time.</p>
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          <Button variant="outline" onClick={handleAddRule}>
            <Plus className="h-4 w-4 mr-1" />
            Add Rule
          </Button>

          <Button
            onClick={handleSave}
            disabled={updateSettings.isPending || !hasChanges}
          >
            {updateSettings.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            Save
          </Button>
        </div>

        <p className="text-xs text-muted-foreground">
          Changes take effect on the next EPG generation. Existing channel streams will be reordered.
        </p>
      </CardContent>
    </Card>
  )
}
