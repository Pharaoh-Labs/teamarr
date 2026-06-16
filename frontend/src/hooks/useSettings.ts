import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getSettings,
  getDispatcharrSettings,
  updateDispatcharrSettings,
  testDispatcharrConnection,
  getDispatcharrStatus,
  getDispatcharrEPGSources,
  getLifecycleSettings,
  updateLifecycleSettings,
  getSchedulerSettings,
  updateSchedulerSettings,
  getSchedulerStatus,
  getEPGSettings,
  updateEPGSettings,
  getDurationSettings,
  updateDurationSettings,
  getReconciliationSettings,
  updateReconciliationSettings,
  getDisplaySettings,
  updateDisplaySettings,
  getTeamFilterSettings,
  updateTeamFilterSettings,
  getExceptionKeywords,
  createExceptionKeyword,
  updateExceptionKeyword,
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
import type {
  DispatcharrSettings,
  LifecycleSettings,
  SchedulerSettingsUpdate,
  EPGSettings,
  DurationSettings,
  ReconciliationSettings,
  DisplaySettings,
  TeamFilterSettingsUpdate,
  ChannelNumberingSettingsUpdate,
  StreamOrderingSettingsUpdate,
  UpdateCheckSettingsUpdate,
  FeedSeparationSettingsUpdate,
  EmbySettings,
  JellyfinSettings,
  ChannelsDVRSettings,
} from "@/api/settings"

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  })
}

export function useDispatcharrSettings() {
  return useQuery({
    queryKey: ["settings", "dispatcharr"],
    queryFn: getDispatcharrSettings,
  })
}

export function useUpdateDispatcharrSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: Partial<DispatcharrSettings>) =>
      updateDispatcharrSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useTestDispatcharrConnection() {
  return useMutation({
    mutationFn: (data?: { url?: string; username?: string; password?: string }) =>
      testDispatcharrConnection(data),
  })
}

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

export function useLifecycleSettings() {
  return useQuery({
    queryKey: ["settings", "lifecycle"],
    queryFn: getLifecycleSettings,
  })
}

export function useUpdateLifecycleSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: LifecycleSettings) => updateLifecycleSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useSchedulerSettings() {
  return useQuery({
    queryKey: ["settings", "scheduler"],
    queryFn: getSchedulerSettings,
  })
}

export function useUpdateSchedulerSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: SchedulerSettingsUpdate) => updateSchedulerSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
      queryClient.invalidateQueries({ queryKey: ["scheduler"] })
    },
  })
}

export function useSchedulerStatus() {
  return useQuery({
    queryKey: ["scheduler", "status"],
    queryFn: getSchedulerStatus,
    refetchInterval: 10000, // Refresh every 10 seconds
  })
}

export function useEPGSettings() {
  return useQuery({
    queryKey: ["settings", "epg"],
    queryFn: getEPGSettings,
  })
}

export function useUpdateEPGSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: EPGSettings) => updateEPGSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useDurationSettings() {
  return useQuery({
    queryKey: ["settings", "durations"],
    queryFn: getDurationSettings,
  })
}

export function useUpdateDurationSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: DurationSettings) => updateDurationSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useReconciliationSettings() {
  return useQuery({
    queryKey: ["settings", "reconciliation"],
    queryFn: getReconciliationSettings,
  })
}

export function useUpdateReconciliationSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: ReconciliationSettings) =>
      updateReconciliationSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useDisplaySettings() {
  return useQuery({
    queryKey: ["settings", "display"],
    queryFn: getDisplaySettings,
  })
}

export function useUpdateDisplaySettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: DisplaySettings) => updateDisplaySettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useTeamFilterSettings() {
  return useQuery({
    queryKey: ["settings", "team-filter"],
    queryFn: getTeamFilterSettings,
  })
}

export function useUpdateTeamFilterSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: TeamFilterSettingsUpdate) => updateTeamFilterSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

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

export function useUpdateExceptionKeyword() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<{ label: string; match_terms: string; behavior: string; enabled: boolean }> }) =>
      updateExceptionKeyword(id, data),
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

export function useChannelNumberingSettings() {
  return useQuery({
    queryKey: ["settings", "channel-numbering"],
    queryFn: getChannelNumberingSettings,
  })
}

export function useUpdateChannelNumberingSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: ChannelNumberingSettingsUpdate) =>
      updateChannelNumberingSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useStreamOrderingSettings() {
  return useQuery({
    queryKey: ["settings", "stream-ordering"],
    queryFn: getStreamOrderingSettings,
  })
}

export function useUpdateStreamOrderingSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: StreamOrderingSettingsUpdate) =>
      updateStreamOrderingSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useUpdateCheckSettings() {
  return useQuery({
    queryKey: ["settings", "update-check"],
    queryFn: getUpdateCheckSettings,
  })
}

export function useUpdateUpdateCheckSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: UpdateCheckSettingsUpdate) =>
      updateUpdateCheckSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

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

export function useFeedSeparationSettings() {
  return useQuery({
    queryKey: ["settings", "feed-separation"],
    queryFn: getFeedSeparationSettings,
  })
}

export function useUpdateFeedSeparationSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: FeedSeparationSettingsUpdate) =>
      updateFeedSeparationSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

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

// Emby Settings Hooks
export function useEmbySettings() {
  return useQuery({
    queryKey: ["settings", "emby"],
    queryFn: getEmbySettings,
  })
}

export function useUpdateEmbySettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: Partial<EmbySettings>) =>
      updateEmbySettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useTestEmbyConnection() {
  return useMutation({
    mutationFn: (data?: { url?: string; username?: string; password?: string; api_key?: string }) =>
      testEmbyConnection(data),
  })
}

// Jellyfin Settings Hooks
export function useJellyfinSettings() {
  return useQuery({
    queryKey: ["settings", "jellyfin"],
    queryFn: getJellyfinSettings,
  })
}

export function useUpdateJellyfinSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: Partial<JellyfinSettings>) =>
      updateJellyfinSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useTestJellyfinConnection() {
  return useMutation({
    mutationFn: (data?: { url?: string; username?: string; password?: string; api_key?: string }) =>
      testJellyfinConnection(data),
  })
}

// Channels DVR Settings Hooks
export function useChannelsDVRSettings() {
  return useQuery({
    queryKey: ["settings", "channelsdvr"],
    queryFn: getChannelsDVRSettings,
  })
}

export function useUpdateChannelsDVRSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: Partial<ChannelsDVRSettings>) =>
      updateChannelsDVRSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
      queryClient.invalidateQueries({ queryKey: ["channelsdvr", "sources"] })
      queryClient.invalidateQueries({ queryKey: ["channelsdvr", "lineups"] })
    },
  })
}

export function useTestChannelsDVRConnection() {
  return useMutation({
    mutationFn: (data?: { url?: string; source_name?: string }) =>
      testChannelsDVRConnection(data),
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
