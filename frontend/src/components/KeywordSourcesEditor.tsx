import { useEffect, useMemo, useState } from "react"
import { LoaderCircle, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { CheckboxListPicker } from "@/components/ui/checkbox-list-picker"
import { SelectedBadges } from "@/components/ui/selected-badges"
import { useChannelGroups } from "@/hooks/useDispatcharr"
import { useGroups } from "@/hooks/useGroups"
import { getRawStreams, previewGroupPattern, type GroupPatternPreview, type RawStream } from "@/api/groups"
import type { KeywordMatchSources, KeywordSourceRef } from "@/api/settings"
import { validateRegex } from "@/lib/regex-utils"

const STREAM_RESULTS_SHOWN = 50

/**
 * Editor for an exception keyword's match sources (#893): M3U group regex
 * and picks, stream regex and pins, and event groups. Patterns are stored in
 * Python regex syntax, like the event-group name pattern.
 */
export function KeywordSourcesEditor({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: KeywordMatchSources
  saving: boolean
  onSave: (sources: KeywordMatchSources) => void
  onCancel: () => void
}) {
  const [sources, setSources] = useState<KeywordMatchSources>(initial)
  const set = (patch: Partial<KeywordMatchSources>) => setSources((prev) => ({ ...prev, ...patch }))

  const groupPattern = sources.m3u_group_pattern ?? ""
  const streamPattern = sources.stream_pattern ?? ""
  const groupPatternCheck = groupPattern.trim() ? validateRegex(groupPattern) : null
  const streamPatternCheck = streamPattern.trim() ? validateRegex(streamPattern) : null
  const invalid = groupPatternCheck?.valid === false || streamPatternCheck?.valid === false

  return (
    <div className="space-y-4 rounded-md border bg-muted/30 p-4">
      <p className="text-xs text-muted-foreground">
        Tag streams by where they come from, not only by their name. Checked in this order, first
        match wins: pinned streams, stream name (terms, then regex), EPG programme, picked M3U
        groups, M3U group regex, event groups.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-sm">M3U group regex</Label>
          <Input
            value={groupPattern}
            onChange={(e) => set({ m3u_group_pattern: e.target.value || null })}
            placeholder={String.raw`e.g. ^(ES|LA)\|`}
            className="font-mono text-sm"
          />
          <GroupPatternPreviewLine pattern={groupPattern} invalid={groupPatternCheck?.valid === false} />
        </div>

        <div className="space-y-1">
          <Label className="text-sm">Stream name regex</Label>
          <Input
            value={streamPattern}
            onChange={(e) => set({ stream_pattern: e.target.value || null })}
            placeholder={String.raw`e.g. \((MX|ES)\)`}
            className="font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">
            {streamPatternCheck?.valid === false
              ? `Invalid regular expression: ${streamPatternCheck.error}`
              : "Case-insensitive. Use for patterns the comma-separated match terms can't express."}
          </p>
        </div>
      </div>

      <M3UGroupPicker selected={sources.m3u_groups} onChange={(m3u_groups) => set({ m3u_groups })} />

      <EventGroupPicker
        selected={sources.event_group_ids}
        onChange={(event_group_ids) => set({ event_group_ids })}
      />

      <StreamPinner selected={sources.streams} onChange={(streams) => set({ streams })} />

      <div className="flex gap-2">
        <Button size="sm" onClick={() => onSave(sources)} disabled={saving || invalid}>
          {saving && <LoaderCircle className="mr-1 h-4 w-4 animate-spin" />}
          Save sources
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function GroupPatternPreviewLine({ pattern, invalid }: { pattern: string; invalid: boolean }) {
  // Keyed by the pattern it was computed for, like the event-group form's
  // preview, so a stale answer is never shown for a newer pattern.
  const [result, setResult] = useState<{ forPattern: string; data: GroupPatternPreview | null } | null>(
    null
  )

  useEffect(() => {
    if (!pattern.trim() || invalid) return
    const handle = setTimeout(async () => {
      try {
        setResult({ forPattern: pattern, data: await previewGroupPattern(pattern) })
      } catch {
        setResult({ forPattern: pattern, data: null })
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [pattern, invalid])

  const preview = result?.forPattern === pattern ? result.data : undefined
  let text: string
  if (!pattern.trim()) text = "Case-insensitive, matched against the stream's M3U group name."
  else if (invalid) text = "Invalid regular expression."
  else if (preview === undefined) text = "Checking…"
  else if (preview === null) text = "Preview unavailable (Dispatcharr not reachable)."
  else if (preview.total === 0) text = "Matches no live M3U groups."
  else
    text = `Matches ${preview.total} group${preview.total === 1 ? "" : "s"}: ${preview.matches
      .slice(0, 5)
      .map((m) => m.name)
      .join(", ")}${preview.total > 5 ? ", …" : ""}`
  return <p className="text-xs text-muted-foreground">{text}</p>
}

function M3UGroupPicker({
  selected,
  onChange,
}: {
  selected: KeywordSourceRef[]
  onChange: (refs: KeywordSourceRef[]) => void
}) {
  const [open, setOpen] = useState(false)
  const groupsQuery = useChannelGroups(false, open)
  const items = useMemo(
    () =>
      (groupsQuery.data ?? [])
        .filter((g) => g.from_m3u)
        .map((g) => ({ value: String(g.id), label: g.name })),
    [groupsQuery.data]
  )
  const namesById = useMemo(() => new Map(items.map((i) => [i.value, i.label])), [items])

  return (
    <div className="space-y-1">
      <Label className="text-sm">M3U groups</Label>
      <SelectedBadges
        items={selected.map((g) => ({ key: String(g.id), label: g.name ?? `#${g.id}` }))}
        onRemove={(key) => onChange(selected.filter((g) => String(g.id) !== key))}
      />
      {open ? (
        groupsQuery.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading M3U groups…</p>
        ) : (
          <CheckboxListPicker
            items={items}
            selected={selected.map((g) => String(g.id))}
            onChange={(values) =>
              onChange(
                values.map((v) => ({
                  id: Number(v),
                  name: namesById.get(v) ?? selected.find((g) => String(g.id) === v)?.name ?? null,
                }))
              )
            }
            searchPlaceholder="Search M3U groups…"
          />
        )
      ) : (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          <Plus className="mr-1 h-3 w-3" /> Pick M3U groups
        </Button>
      )}
    </div>
  )
}

function EventGroupPicker({
  selected,
  onChange,
}: {
  selected: number[]
  onChange: (ids: number[]) => void
}) {
  const groupsQuery = useGroups(true)
  const items = useMemo(
    () =>
      (groupsQuery.data?.groups ?? []).map((g) => ({
        value: String(g.id),
        label: g.display_name || g.name,
      })),
    [groupsQuery.data]
  )
  return (
    <div className="space-y-1">
      <Label className="text-sm">Event groups</Label>
      <CheckboxListPicker
        items={items}
        selected={selected.map(String)}
        onChange={(values) => onChange(values.map(Number))}
        searchPlaceholder="Search event groups…"
        maxHeight="max-h-32"
      />
    </div>
  )
}

function StreamPinner({
  selected,
  onChange,
}: {
  selected: KeywordSourceRef[]
  onChange: (refs: KeywordSourceRef[]) => void
}) {
  const groupsQuery = useGroups(true)
  const [groupId, setGroupId] = useState<number | null>(null)
  const [streams, setStreams] = useState<{ forGroup: number; list: RawStream[] | null } | null>(null)
  const [search, setSearch] = useState("")

  useEffect(() => {
    if (groupId === null) return
    let cancelled = false
    getRawStreams(groupId)
      .then((r) => !cancelled && setStreams({ forGroup: groupId, list: r.streams }))
      .catch(() => !cancelled && setStreams({ forGroup: groupId, list: null }))
    return () => {
      cancelled = true
    }
  }, [groupId])

  const loaded = streams?.forGroup === groupId ? streams.list : undefined
  const pinned = useMemo(() => new Set(selected.map((s) => s.id)), [selected])
  const matches = useMemo(() => {
    if (!loaded) return []
    const q = search.trim().toLowerCase()
    return loaded.filter((s) => !pinned.has(s.stream_id) && (!q || s.stream_name.toLowerCase().includes(q)))
  }, [loaded, search, pinned])

  return (
    <div className="space-y-1">
      <Label className="text-sm">Pinned streams</Label>
      <SelectedBadges
        items={selected.map((s) => ({ key: String(s.id), label: s.name ?? `#${s.id}` }))}
        onRemove={(key) => onChange(selected.filter((s) => String(s.id) !== key))}
        maxBadges={20}
      />
      <div className="flex flex-col gap-2 sm:flex-row">
        <Select
          value={groupId === null ? "" : String(groupId)}
          onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)}
          className="sm:w-56"
        >
          <option value="">Pin streams from event group…</option>
          {(groupsQuery.data?.groups ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.display_name || g.name}
            </option>
          ))}
        </Select>
        {groupId !== null && (
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter streams…"
            className="sm:flex-1"
          />
        )}
      </div>
      {groupId !== null && (
        <div className="max-h-48 overflow-y-auto rounded-md border">
          {loaded === undefined ? (
            <p className="p-2 text-xs text-muted-foreground">Loading streams…</p>
          ) : loaded === null ? (
            <p className="p-2 text-xs text-muted-foreground">Streams unavailable (Dispatcharr not reachable).</p>
          ) : matches.length === 0 ? (
            <p className="p-2 text-xs text-muted-foreground">No streams match.</p>
          ) : (
            <>
              {matches.slice(0, STREAM_RESULTS_SHOWN).map((s) => (
                <button
                  key={s.stream_id}
                  type="button"
                  onClick={() => onChange([...selected, { id: s.stream_id, name: s.stream_name }])}
                  className="block w-full truncate px-2 py-1 text-left text-xs hover:bg-muted"
                  title={`Pin #${s.stream_id}`}
                >
                  <Plus className="mr-1 inline h-3 w-3" />
                  {s.stream_name}
                </button>
              ))}
              {matches.length > STREAM_RESULTS_SHOWN && (
                <p className="px-2 py-1 text-xs text-muted-foreground">
                  {matches.length - STREAM_RESULTS_SHOWN} more — narrow the filter.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
