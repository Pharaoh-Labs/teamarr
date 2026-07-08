/**
 * API client for Dispatcharr proxy endpoints (channel/stream profiles, channel groups).
 *
 * The backend returns 503 when Dispatcharr is not configured or unreachable;
 * list fetchers map that to an empty list so selectors degrade gracefully.
 */

import { api, ApiError } from "./client"

export interface ChannelProfile {
  id: number
  name: string
}

export interface StreamProfile {
  id: number
  name: string
  command: string
}

export interface ChannelGroup {
  id: number
  name: string
  from_m3u: boolean
}

async function emptyOn503<T>(promise: Promise<T[]>): Promise<T[]> {
  try {
    return await promise
  } catch (err) {
    if (err instanceof ApiError && err.status === 503) return []
    throw err
  }
}

export function getChannelProfiles(): Promise<ChannelProfile[]> {
  return emptyOn503(api.get<ChannelProfile[]>("/dispatcharr/channel-profiles"))
}

export function createChannelProfile(name: string): Promise<ChannelProfile> {
  return api.post<ChannelProfile>(
    `/dispatcharr/channel-profiles?name=${encodeURIComponent(name)}`
  )
}

export function getStreamProfiles(): Promise<StreamProfile[]> {
  return emptyOn503(api.get<StreamProfile[]>("/dispatcharr/stream-profiles"))
}

export function getChannelGroups(excludeM3u: boolean): Promise<ChannelGroup[]> {
  return emptyOn503(
    api.get<ChannelGroup[]>(`/dispatcharr/channel-groups?exclude_m3u=${excludeM3u}`)
  )
}
