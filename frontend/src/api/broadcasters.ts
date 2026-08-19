import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

export interface BroadcasterMapping {
  id: number
  name: string
  pattern: string
  pattern_type: "regex" | "exact" | "tvg_id" | "channel_id"
  team_id: string
  team_name?: string | null
  league: string
  is_active: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface BroadcasterMappingCreate {
  name: string
  pattern: string
  pattern_type?: "regex" | "exact" | "tvg_id" | "channel_id"
  team_id: string
  team_name?: string | null
  league?: string
  is_active?: boolean
}

export interface BroadcasterMappingUpdate {
  name?: string
  pattern?: string
  pattern_type?: "regex" | "exact" | "tvg_id" | "channel_id"
  team_id?: string
  team_name?: string | null
  league?: string
  is_active?: boolean
}

export interface RSNCatalogEntry {
  network_name: string
  league: string
  team_abbreviation: string
  patterns: string[]
  is_ambiguous: boolean
  team_synonyms: string[]
}

const API_BASE = "/api/v1/broadcasters"

export function useBroadcasters(league?: string, activeOnly?: boolean) {
  return useQuery<BroadcasterMapping[]>({
    queryKey: ["broadcasters", league, activeOnly],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (league) params.append("league", league)
      if (activeOnly) params.append("active_only", "true")
      const query = params.toString() ? `?${params.toString()}` : ""
      const res = await fetch(`${API_BASE}/${query}`)
      if (!res.ok) throw new Error("Failed to fetch broadcaster mappings")
      return res.json()
    },
  })
}

export function useRsnCatalog(league: string = "mlb") {
  return useQuery<RSNCatalogEntry[]>({
    queryKey: ["rsn_catalog", league],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/catalog?league=${encodeURIComponent(league)}`)
      if (!res.ok) throw new Error("Failed to fetch RSN catalog")
      return res.json()
    },
  })
}

export function useCreateBroadcaster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data: BroadcasterMappingCreate) => {
      const res = await fetch(`${API_BASE}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      })
      if (!res.ok) {
        const error = await res.json().catch(() => ({}))
        throw new Error(error.detail || "Failed to create broadcaster mapping")
      }
      return res.json() as Promise<BroadcasterMapping>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["broadcasters"] })
    },
  })
}

export function useUpdateBroadcaster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: BroadcasterMappingUpdate }) => {
      const res = await fetch(`${API_BASE}/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      })
      if (!res.ok) {
        const error = await res.json().catch(() => ({}))
        throw new Error(error.detail || "Failed to update broadcaster mapping")
      }
      return res.json() as Promise<BroadcasterMapping>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["broadcasters"] })
    },
  })
}

export function useDeleteBroadcaster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE}/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error("Failed to delete broadcaster mapping")
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["broadcasters"] })
    },
  })
}
