import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  type CustomLeagueCreate,
  type CustomLeagueUpdate,
  createCustomLeague,
  deleteCustomLeague,
  getCustomLeagueCapability,
  listCustomLeagues,
  testCustomLeague,
  updateCustomLeague,
} from "@/api/customLeagues"

/** Premium-gate state + the allowed sport list for the form dropdown. */
export function useCustomLeagueCapability() {
  return useQuery({
    queryKey: ["custom-leagues", "capability"],
    queryFn: getCustomLeagueCapability,
    staleTime: 1000 * 60 * 5,
  })
}

export function useCustomLeagues() {
  return useQuery({
    queryKey: ["custom-leagues"],
    queryFn: listCustomLeagues,
  })
}

/** Live TSDB validation — not cached; each press is a fresh check. */
export function useTestCustomLeague() {
  return useMutation({ mutationFn: testCustomLeague })
}

export function useCreateCustomLeague() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CustomLeagueCreate) => createCustomLeague(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["custom-leagues"] }),
  })
}

export function useUpdateCustomLeague() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ leagueCode, data }: { leagueCode: string; data: CustomLeagueUpdate }) =>
      updateCustomLeague(leagueCode, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["custom-leagues"] }),
  })
}

export function useDeleteCustomLeague() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (leagueCode: string) => deleteCustomLeague(leagueCode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["custom-leagues"] }),
  })
}
