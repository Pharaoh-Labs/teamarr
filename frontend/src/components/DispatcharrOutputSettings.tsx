import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { SaveButton as SaveButtonBase } from "@/components/ui/save-button"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Select } from "@/components/ui/select"
import {
  ChannelProfileSelector,
  profileIdsToApi,
  apiToProfileIds,
} from "@/components/ChannelProfileSelector"
import { StreamProfileSelector } from "@/components/StreamProfileSelector"
import {
  useSettings,
  useDispatcharrStatus,
  useUpdateDispatcharrSettings,
} from "@/hooks/useSettings"
import type { DispatcharrSettings } from "@/api/settings"

/**
 * Dispatcharr Output — default channel profiles, stream profile, and channel
 * group (+ mode). Lifted out of the Settings Dispatcharr tab into the Channels
 * home (v2.7.0 IA); connection/credentials, EPG source, and logo cleanup (a
 * housekeeping behavior, not channel routing) stay in Settings → Dispatcharr.
 * Self-contained via its own hooks. cleanup_unused_logos is still round-tripped
 * in the save below so writing channel-output settings never resets it.
 *
 * SAFETY: the save replicates Settings' handleSaveDispatcharr exactly — it sends
 * the FULL Dispatcharr blob (url/username/epg_id loaded fresh from settings +
 * the profile/group/logo fields edited here) and only includes the password when
 * the user actually changed it. The PUT route maps an omitted profile/group field
 * to NULL, so the full-blob send is what prevents this card from wiping either the
 * credentials or the profile/group config. Do not narrow it to a partial payload.
 */
export function DispatcharrOutputSettings() {
  const { data: settings } = useSettings()
  const dispatcharrStatus = useDispatcharrStatus()
  const updateDispatcharr = useUpdateDispatcharrSettings()

  // Fetch channel profiles for conversion helpers
  const channelProfilesQuery = useQuery({
    queryKey: ["dispatcharr-channel-profiles"],
    queryFn: async () => {
      const response = await fetch("/api/v1/dispatcharr/channel-profiles")
      if (!response.ok) return []
      return response.json() as Promise<{ id: number; name: string }[]>
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })

  // Always fetch the full group list (with from_m3u flag) so a saved M3U-sourced
  // group always has a matching <option> to bind to (teamarrv2-t6d). The
  // includeM3uGroups toggle filters the displayed list; the selected group is
  // always kept visible.
  const [includeM3uGroups, setIncludeM3uGroups] = useState(false)
  const channelGroupsQuery = useQuery({
    queryKey: ["dispatcharr-channel-groups"],
    queryFn: async () => {
      const response = await fetch(
        "/api/v1/dispatcharr/channel-groups?exclude_m3u=false"
      )
      if (!response.ok) return []
      return response.json() as Promise<
        { id: number; name: string; from_m3u: boolean }[]
      >
    },
    enabled: dispatcharrStatus.data?.connected ?? false,
    retry: false,
  })

  const visibleChannelGroups = (
    all: { id: number; name: string; from_m3u: boolean }[],
    selectedId: number | null | undefined,
  ) => {
    if (includeM3uGroups) return all
    return all.filter((g) => !g.from_m3u || g.id === selectedId)
  }

  // Local form state — initialized from the FULL dispatcharr blob so the save
  // can round-trip every field (password intentionally blank: never edited here).
  const [dispatcharr, setDispatcharr] = useState<Partial<DispatcharrSettings>>({})
  const [selectedProfileIds, setSelectedProfileIds] = useState<(number | string)[]>([])

  useEffect(() => {
    if (settings) {
      setDispatcharr({
        enabled: settings.dispatcharr.enabled,
        url: settings.dispatcharr.url,
        username: settings.dispatcharr.username,
        password: "", // Don't show masked password
        epg_id: settings.dispatcharr.epg_id,
        default_channel_profile_ids: settings.dispatcharr.default_channel_profile_ids,
        default_stream_profile_id: settings.dispatcharr.default_stream_profile_id,
        default_channel_group_id: settings.dispatcharr.default_channel_group_id,
        default_channel_group_mode: settings.dispatcharr.default_channel_group_mode,
        cleanup_unused_logos: settings.dispatcharr.cleanup_unused_logos,
      })
    }
  }, [settings])

  // Convert API profile IDs to display IDs when profiles are loaded
  useEffect(() => {
    if (channelProfilesQuery.data && settings) {
      const allProfileIds = channelProfilesQuery.data.map((p) => p.id)
      const displayIds = apiToProfileIds(
        settings.dispatcharr.default_channel_profile_ids,
        allProfileIds
      )
      setSelectedProfileIds(displayIds)
    }
  }, [channelProfilesQuery.data, settings])

  const handleSave = async () => {
    try {
      // Convert selected profile IDs to API format
      // All selected → null (backend sends [0] sentinel to Dispatcharr)
      // None selected → [] (no profiles)
      // Some selected → those specific IDs
      const allProfileIds = channelProfilesQuery.data?.map((p) => p.id) ?? []
      const profileIdsToSave = profileIdsToApi(selectedProfileIds, allProfileIds)

      // Full-blob save (see component docstring). Only send password if changed.
      const data: Partial<DispatcharrSettings> = {
        enabled: dispatcharr.enabled,
        url: dispatcharr.url,
        username: dispatcharr.username,
        epg_id: dispatcharr.epg_id,
        default_channel_profile_ids: profileIdsToSave,
        default_stream_profile_id: dispatcharr.default_stream_profile_id,
        default_channel_group_id: dispatcharr.default_channel_group_id,
        default_channel_group_mode: dispatcharr.default_channel_group_mode,
        cleanup_unused_logos: dispatcharr.cleanup_unused_logos,
      }
      if (dispatcharr.password) {
        data.password = dispatcharr.password
      }
      await updateDispatcharr.mutateAsync(data)
      toast.success("Dispatcharr output settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const SaveButton = () => (
    <SaveButtonBase onClick={handleSave} pending={updateDispatcharr.isPending} />
  )

  return (
    <div className="space-y-3">
      {/* Default Channel Profiles */}
      <Card>
        <CardHeader>
          <CardTitle>Default Channel Profiles</CardTitle>
          <CardDescription>Profiles assigned to new channels</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <ChannelProfileSelector
              selectedIds={selectedProfileIds}
              onChange={setSelectedProfileIds}
              disabled={!dispatcharrStatus.data?.connected}
            />
            <p className="text-xs text-muted-foreground">
              These defaults apply to all groups unless overridden in individual group settings.
              Profile assignment is enforced on every EPG generation run.
            </p>
          </div>
          <SaveButton />
        </CardContent>
      </Card>

      {/* Default Stream Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Default Stream Profile</CardTitle>
          <CardDescription>Processing profile for channel streams</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <StreamProfileSelector
              value={dispatcharr.default_stream_profile_id ?? null}
              onChange={(id) => setDispatcharr({ ...dispatcharr, default_stream_profile_id: id })}
              disabled={!dispatcharrStatus.data?.connected}
              isGlobalDefault
            />
            <p className="text-xs text-muted-foreground">
              Stream profile defines how streams are processed (ffmpeg, VLC, proxy, etc).
              This default applies to all groups unless overridden.
            </p>
          </div>
          <SaveButton />
        </CardContent>
      </Card>

      {/* Default Channel Group */}
      <Card>
        <CardHeader>
          <CardTitle>Default Channel Group</CardTitle>
          <CardDescription>Default group and mode for event channels</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-sm font-medium">Channel Group</Label>
            <Select
              value={dispatcharr.default_channel_group_id?.toString() ?? ""}
              onChange={(e) => {
                const v = e.target.value
                setDispatcharr({
                  ...dispatcharr,
                  default_channel_group_id: v ? parseInt(v) : null,
                })
              }}
              disabled={!dispatcharrStatus.data?.connected}
              className="w-64"
            >
              <option value="">None</option>
              {visibleChannelGroups(
                channelGroupsQuery.data ?? [],
                dispatcharr.default_channel_group_id,
              ).map((g) => (
                <option key={g.id} value={g.id.toString()}>
                  {g.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Static group used when mode is "Static". Per-league overrides take priority.
            </p>
            <div className="flex items-center gap-2 pt-1">
              <Switch
                id="include-m3u-groups"
                checked={includeM3uGroups}
                onCheckedChange={setIncludeM3uGroups}
                disabled={!dispatcharrStatus.data?.connected}
              />
              <Label htmlFor="include-m3u-groups" className="text-xs font-normal cursor-pointer">
                Show M3U-sourced channel groups
              </Label>
            </div>
            <p className="text-xs text-muted-foreground">
              Off by default. Enable to assign groups that originated from an M3U
              account (e.g., a group you manually curated that's also tagged with an M3U source).
            </p>
          </div>

          <div className="space-y-2">
            <Label className="text-sm font-medium">Group Mode</Label>
            <Select
              value={
                dispatcharr.default_channel_group_mode &&
                !["static", "sport", "league"].includes(dispatcharr.default_channel_group_mode)
                  ? "custom"
                  : dispatcharr.default_channel_group_mode ?? "static"
              }
              onChange={(e) => {
                const v = e.target.value
                if (v === "custom") {
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: "{sport} | {league}" })
                } else {
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: v || "static" })
                }
              }}
              className="w-64"
            >
              <option value="static">Static (use selected group)</option>
              <option value="sport">Dynamic by Sport</option>
              <option value="league">Dynamic by League</option>
              <option value="custom">Custom pattern</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              Static uses the group above. Dynamic modes auto-create groups named by sport or league.
              Custom lets you define a pattern with {"{sport}"} and {"{league}"} placeholders.
            </p>
          </div>

          {dispatcharr.default_channel_group_mode &&
            !["static", "sport", "league"].includes(dispatcharr.default_channel_group_mode) && (
            <div className="space-y-2">
              <Label className="text-sm font-medium">Custom Pattern</Label>
              <Input
                value={dispatcharr.default_channel_group_mode}
                onChange={(e) =>
                  setDispatcharr({ ...dispatcharr, default_channel_group_mode: e.target.value })
                }
                placeholder="{sport} | {league}"
                className="w-64"
              />
              <p className="text-xs text-muted-foreground">
                Use {"{sport}"} and {"{league}"} as placeholders. Example: "{"{sport}"} | {"{league}"}" creates groups like "Hockey | NHL".
              </p>
            </div>
          )}

          <SaveButton />
        </CardContent>
      </Card>
    </div>
  )
}
