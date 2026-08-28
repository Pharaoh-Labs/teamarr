/**
 * Hooks for Dispatcharr proxy data (channel/stream profiles, channel groups).
 *
 * All queries use retry: false — when Dispatcharr is down the backend answers
 * 503 (mapped to []) and retrying just delays the empty state.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getChannelGroups,
  getChannelGroupsWithChannels,
  getChannelProfiles,
  getStreamProfiles,
  createChannelProfile,
} from "@/api/dispatcharr"

export function useChannelProfiles(enabled = true) {
  return useQuery({
    queryKey: ["dispatcharr-channel-profiles"],
    queryFn: getChannelProfiles,
    enabled,
    retry: false,
  })
}

export function useStreamProfiles(enabled = true) {
  return useQuery({
    queryKey: ["dispatcharr-stream-profiles"],
    queryFn: getStreamProfiles,
    enabled,
    retry: false,
  })
}

export function useChannelGroups(excludeM3u: boolean, enabled = true) {
  return useQuery({
    // excludeM3u is part of the key — the two variants return different lists
    // and must not share a cache entry.
    queryKey: ["dispatcharr-channel-groups", { excludeM3u }],
    queryFn: () => getChannelGroups(excludeM3u),
    enabled,
    retry: false,
  })
}

/**
 * Channel groups that hold at least one non-Teamarr channel (#631).
 *
 * Separate cache key from useChannelGroups — a different, smaller list.
 */
export function useChannelGroupsWithChannels(enabled = true) {
  return useQuery({
    queryKey: ["dispatcharr-channel-groups", { withChannels: true }],
    queryFn: getChannelGroupsWithChannels,
    enabled,
    retry: false,
  })
}

export function useCreateChannelProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createChannelProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dispatcharr-channel-profiles"] })
    },
  })
}
