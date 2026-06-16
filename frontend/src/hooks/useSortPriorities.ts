import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getSortPriorities,
  getActiveSortPriorities,
  createSortPriority,
  deleteSortPrioritySport,
  deleteSortPriorityLeague,
  reorderSortPriorities,
  autoPopulateSortPriorities,
  getPriorityTeams,
  addPriorityTeam,
  deletePriorityTeam,
} from "@/api/sortPriorities"
import type { SortPriorityCreate, SortPriorityReorderItem } from "@/api/sortPriorities"
import type { TeamFilterEntry } from "@/api/types"

export function useSortPriorities() {
  return useQuery({
    queryKey: ["sort-priorities"],
    queryFn: getSortPriorities,
  })
}

export function useActiveSortPriorities() {
  return useQuery({
    queryKey: ["sort-priorities", "active"],
    queryFn: getActiveSortPriorities,
  })
}

export function useCreateSortPriority() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: SortPriorityCreate) => createSortPriority(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sort-priorities"] })
    },
  })
}

export function useDeleteSortPriority() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sport, leagueCode }: { sport: string; leagueCode?: string | null }) => {
      if (leagueCode) {
        return deleteSortPriorityLeague(sport, leagueCode)
      }
      return deleteSortPrioritySport(sport)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sort-priorities"] })
    },
  })
}

export function useReorderSortPriorities() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (orderedList: SortPriorityReorderItem[]) =>
      reorderSortPriorities(orderedList),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sort-priorities"] })
    },
  })
}

export function useAutoPopulateSortPriorities() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: autoPopulateSortPriorities,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sort-priorities"] })
    },
  })
}

// --- Priority teams ---

export function usePriorityTeams() {
  return useQuery({
    queryKey: ["priority-teams"],
    queryFn: getPriorityTeams,
  })
}

export function useAddPriorityTeam() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (team: TeamFilterEntry) => addPriorityTeam(team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["priority-teams"] })
    },
  })
}

export function useDeletePriorityTeam() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: number) => deletePriorityTeam(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["priority-teams"] })
    },
  })
}
