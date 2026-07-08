import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query"
import {
  getSettings,
  updateDispatcharrSettings,
  testDispatcharrConnection,
  getDispatcharrStatus,
  getDispatcharrEPGSources,
  updateLifecycleSettings,
  getSchedulerSettings,
  updateSchedulerSettings,
  getSchedulerStatus,
  getEPGSettings,
  updateEPGSettings,
  getDurationSettings,
  updateDurationSettings,
  getDisplaySettings,
  updateDisplaySettings,
  getTeamFilterSettings,
  updateTeamFilterSettings,
  getExceptionKeywords,
  createExceptionKeyword,
  deleteExceptionKeyword,
  getChannelNumberingSettings,
  updateChannelNumberingSettings,
  getStreamOrderingSettings,
  updateStreamOrderingSettings,
  getUpdateCheckSettings,
  updateUpdateCheckSettings,
  checkForUpdates,
  getFeedSeparationSettings,
  updateFeedSeparationSettings,
  getLeagueConfigs,
  upsertLeagueConfig,
  deleteLeagueConfig,
  getEmbySettings,
  updateEmbySettings,
  testEmbyConnection,
  getJellyfinSettings,
  updateJellyfinSettings,
  testJellyfinConnection,
  getChannelsDVRSettings,
  updateChannelsDVRSettings,
  testChannelsDVRConnection,
  getChannelsDVRSources,
  getChannelsDVRLineups,
} from "@/api/settings"

// ---------------------------------------------------------------------------
// Factories
//
// Every settings group gets a query hook keyed ["settings", <scope>] and a
// mutation hook with SCOPED invalidation: the all-settings query (exact) plus
// the group's own scoped query and any listed dependents — not the whole
// ["settings"] prefix tree, so saving one group no longer refetches them all.
// ---------------------------------------------------------------------------

const SETTINGS_ROOT: QueryKey = ["settings"]

function settingsQueryHook<T>(scope: string, queryFn: () => Promise<T>) {
  return function useSettingsGroupQuery() {
    return useQuery({ queryKey: ["settings", scope], queryFn })
  }
}

function settingsMutationHook<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  invalidates: QueryKey[] = [],
) {
  return function useSettingsGroupMutation() {
    const queryClient = useQueryClient()
    return useMutation({
      mutationFn,
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: SETTINGS_ROOT, exact: true })
        for (const key of invalidates) {
          queryClient.invalidateQueries({ queryKey: key })
        }
      },
    })
  }
}

// ---------------------------------------------------------------------------
// All settings
// ---------------------------------------------------------------------------

export function useSettings() {
  return useQuery({
    queryKey: SETTINGS_ROOT,
    queryFn: getSettings,
  })
}

// ---------------------------------------------------------------------------
// Settings groups (query + mutation pairs)
// ---------------------------------------------------------------------------

export const useUpdateDispatcharrSettings = settingsMutationHook(updateDispatcharrSettings)

// Lifecycle range changes can arm a channel re-grid (force_channel_relayout_pending)
export const useUpdateLifecycleSettings = settingsMutationHook(updateLifecycleSettings, [
  ["settings", "channel-numbering"],
])

export const useSchedulerSettings = settingsQueryHook("scheduler", getSchedulerSettings)
export const useUpdateSchedulerSettings = settingsMutationHook(updateSchedulerSettings, [
  ["settings", "scheduler"],
  ["scheduler"],
])

export const useEPGSettings = settingsQueryHook("epg", getEPGSettings)
export const useUpdateEPGSettings = settingsMutationHook(updateEPGSettings, [["settings", "epg"]])

export const useDurationSettings = settingsQueryHook("durations", getDurationSettings)
export const useUpdateDurationSettings = settingsMutationHook(updateDurationSettings, [
  ["settings", "durations"],
])

export const useDisplaySettings = settingsQueryHook("display", getDisplaySettings)
export const useUpdateDisplaySettings = settingsMutationHook(updateDisplaySettings, [
  ["settings", "display"],
])

export const useTeamFilterSettings = settingsQueryHook("team-filter", getTeamFilterSettings)
export const useUpdateTeamFilterSettings = settingsMutationHook(updateTeamFilterSettings, [
  ["settings", "team-filter"],
])

export const useChannelNumberingSettings = settingsQueryHook(
  "channel-numbering",
  getChannelNumberingSettings,
)
export const useUpdateChannelNumberingSettings = settingsMutationHook(
  updateChannelNumberingSettings,
  [["settings", "channel-numbering"]],
)

export const useStreamOrderingSettings = settingsQueryHook(
  "stream-ordering",
  getStreamOrderingSettings,
)
export const useUpdateStreamOrderingSettings = settingsMutationHook(updateStreamOrderingSettings, [
  ["settings", "stream-ordering"],
])

export const useUpdateCheckSettings = settingsQueryHook("update-check", getUpdateCheckSettings)
export const useUpdateUpdateCheckSettings = settingsMutationHook(updateUpdateCheckSettings, [
  ["settings", "update-check"],
])

export const useFeedSeparationSettings = settingsQueryHook(
  "feed-separation",
  getFeedSeparationSettings,
)
export const useUpdateFeedSeparationSettings = settingsMutationHook(updateFeedSeparationSettings, [
  ["settings", "feed-separation"],
])

export const useEmbySettings = settingsQueryHook("emby", getEmbySettings)
export const useUpdateEmbySettings = settingsMutationHook(updateEmbySettings, [
  ["settings", "emby"],
])

export const useJellyfinSettings = settingsQueryHook("jellyfin", getJellyfinSettings)
export const useUpdateJellyfinSettings = settingsMutationHook(updateJellyfinSettings, [
  ["settings", "jellyfin"],
])

export const useChannelsDVRSettings = settingsQueryHook("channelsdvr", getChannelsDVRSettings)
export const useUpdateChannelsDVRSettings = settingsMutationHook(updateChannelsDVRSettings, [
  ["settings", "channelsdvr"],
  ["channelsdvr", "sources"],
  ["channelsdvr", "lineups"],
])

// ---------------------------------------------------------------------------
// Connection tests (no cache interaction)
// ---------------------------------------------------------------------------

export function useTestDispatcharrConnection() {
  return useMutation({ mutationFn: testDispatcharrConnection })
}

export function useTestEmbyConnection() {
  return useMutation({ mutationFn: testEmbyConnection })
}

export function useTestJellyfinConnection() {
  return useMutation({ mutationFn: testJellyfinConnection })
}

export function useTestChannelsDVRConnection() {
  return useMutation({ mutationFn: testChannelsDVRConnection })
}

// ---------------------------------------------------------------------------
// Status / discovery queries
// ---------------------------------------------------------------------------

export function useDispatcharrStatus() {
  return useQuery({
    queryKey: ["dispatcharr", "status"],
    queryFn: getDispatcharrStatus,
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

export function useDispatcharrEPGSources(enabled: boolean = true) {
  return useQuery({
    queryKey: ["dispatcharr", "epg-sources"],
    queryFn: getDispatcharrEPGSources,
    enabled, // Only fetch when Dispatcharr is configured
    staleTime: 60000, // 1 minute
  })
}

export function useSchedulerStatus() {
  return useQuery({
    queryKey: ["scheduler", "status"],
    queryFn: getSchedulerStatus,
    refetchInterval: 10000, // Refresh every 10 seconds
  })
}

export function useChannelsDVRSources(url: string | null | undefined) {
  return useQuery({
    queryKey: ["channelsdvr", "sources", url ?? ""],
    queryFn: () => getChannelsDVRSources(url ?? undefined),
    enabled: !!url,
    retry: false,
    staleTime: 30_000,
  })
}

export function useChannelsDVRLineups(url: string | null | undefined) {
  return useQuery({
    queryKey: ["channelsdvr", "lineups", url ?? ""],
    queryFn: () => getChannelsDVRLineups(url ?? undefined),
    enabled: !!url,
    retry: false,
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Update checks
// ---------------------------------------------------------------------------

export function useCheckForUpdates(enabled: boolean = true) {
  return useQuery({
    queryKey: ["updates", "check"],
    queryFn: () => checkForUpdates(false),
    enabled,
    staleTime: 1000 * 60 * 60, // 1 hour (matches backend cache)
    refetchInterval: 1000 * 60 * 60, // Refetch every hour
    refetchOnWindowFocus: false, // Don't spam GitHub API
  })
}

export function useForceCheckForUpdates() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => checkForUpdates(true),
    onSuccess: (data) => {
      queryClient.setQueryData(["updates", "check"], data)
    },
  })
}

// ---------------------------------------------------------------------------
// Exception keywords
// ---------------------------------------------------------------------------

export function useExceptionKeywords(includeDisabled: boolean = false) {
  return useQuery({
    queryKey: ["keywords", { includeDisabled }],
    queryFn: () => getExceptionKeywords(includeDisabled),
  })
}

export function useCreateExceptionKeyword() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: { label: string; match_terms: string; behavior: string; enabled?: boolean }) =>
      createExceptionKeyword(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keywords"] })
    },
  })
}

export function useDeleteExceptionKeyword() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: number) => deleteExceptionKeyword(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keywords"] })
    },
  })
}

// ---------------------------------------------------------------------------
// Per-league channel configs
// ---------------------------------------------------------------------------

export function useLeagueConfigs() {
  return useQuery({
    queryKey: ["league-configs"],
    queryFn: getLeagueConfigs,
  })
}

export function useUpsertLeagueConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ leagueCode, data }: {
      leagueCode: string
      data: {
        channel_profile_ids?: (number | string)[] | null
        channel_group_id?: number | null
        channel_group_mode?: string | null
      }
    }) => upsertLeagueConfig(leagueCode, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["league-configs"] })
    },
  })
}

export function useDeleteLeagueConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (leagueCode: string) => deleteLeagueConfig(leagueCode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["league-configs"] })
    },
  })
}
