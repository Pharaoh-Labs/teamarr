import { api } from "./client"

// Types
export interface EPGSource {
  id: number
  name: string
  url: string
  enabled: boolean
  last_fetched_at: string | null
  last_fetch_status: string | null
  last_fetch_error: string | null
  channel_count: number
  programme_count: number
  created_at: string
  updated_at: string
}

export interface EPGChannel {
  id: number
  source_id: number
  channel_xmltv_id: string
  display_name: string
  icon_url: string | null
  source_name: string
}

export interface StreamMapping {
  id: number
  epg_channel_id: number
  dispatcharr_stream_id: number
  dispatcharr_stream_name: string | null
  m3u_account_id: number | null
  enabled: boolean
  epg_channel_name: string
  channel_xmltv_id: string
  source_id: number
  source_name: string
  source_url: string
  created_at: string
}

export interface EPGProgramme {
  id: number
  channel_id: number
  title: string
  start_time: string
  stop_time: string
  description: string | null
  subtitle: string | null
  categories: string | null
}

export interface DispatcharrStream {
  id: number
  name: string
  group_name: string
  group_id: number
  m3u_account_id: number | null
}

// Sources
export async function listSources(
  includeDisabled = true
): Promise<{ sources: EPGSource[] }> {
  return api.get(`/epg-sources/?include_disabled=${includeDisabled}`)
}

export async function createSource(data: {
  name: string
  url: string
}): Promise<EPGSource> {
  return api.post("/epg-sources/", data)
}

export async function updateSource(
  id: number,
  data: { name?: string; url?: string; enabled?: boolean }
): Promise<EPGSource> {
  return api.put(`/epg-sources/${id}`, data)
}

export async function deleteSource(id: number): Promise<{ success: boolean }> {
  return api.delete(`/epg-sources/${id}`)
}

export async function refreshSource(
  id: number
): Promise<{ success: boolean; channels: number; programmes: number }> {
  return api.post(`/epg-sources/${id}/refresh`)
}

// Channels
export async function listSourceChannels(
  sourceId: number
): Promise<{ channels: EPGChannel[] }> {
  return api.get(`/epg-sources/${sourceId}/channels`)
}

export async function listAllChannels(): Promise<{ channels: EPGChannel[] }> {
  return api.get("/epg-sources/channels/all")
}

// Programmes
export async function listProgrammes(
  channelId: number,
  startAfter?: string,
  endBefore?: string
): Promise<{ programmes: EPGProgramme[] }> {
  const params = new URLSearchParams()
  if (startAfter) params.set("start_after", startAfter)
  if (endBefore) params.set("end_before", endBefore)
  const qs = params.toString()
  return api.get(`/epg-sources/channels/${channelId}/programmes${qs ? `?${qs}` : ""}`)
}

export async function searchProgrammes(
  pattern: string,
  channelId?: number
): Promise<{ programmes: EPGProgramme[] }> {
  return api.post("/epg-sources/programmes/search", {
    pattern,
    channel_id: channelId,
  })
}

// Mappings
export async function listMappings(
  enabledOnly = false
): Promise<{ mappings: StreamMapping[] }> {
  return api.get(`/epg-sources/mappings?enabled_only=${enabledOnly}`)
}

export async function createMapping(data: {
  epg_channel_id: number
  dispatcharr_stream_id: number
  dispatcharr_stream_name?: string
  m3u_account_id?: number
}): Promise<StreamMapping> {
  return api.post("/epg-sources/mappings", data)
}

export async function deleteMapping(
  id: number
): Promise<{ success: boolean }> {
  return api.delete(`/epg-sources/mappings/${id}`)
}

export async function toggleMapping(
  id: number,
  enabled: boolean
): Promise<StreamMapping> {
  return api.patch(`/epg-sources/mappings/${id}`, { enabled })
}

// Dispatcharr streams
export async function getDispatcharrStreams(): Promise<{
  streams: DispatcharrStream[]
  error?: string
}> {
  return api.get("/epg-sources/dispatcharr-streams")
}
