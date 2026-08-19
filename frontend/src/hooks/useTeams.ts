import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { listTeams, updateTeam, deleteTeam } from "@/api/teams"
import type { TeamUpdate } from "@/api/teams"

export function useTeams(activeOnly = false) {
  return useQuery({
    queryKey: ["teams", { activeOnly }],
    queryFn: () => listTeams(activeOnly),
  })
}

export function useUpdateTeam() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ teamId, data }: { teamId: number; data: TeamUpdate }) =>
      updateTeam(teamId, data),
    onSuccess: (_, { teamId }) => {
      queryClient.invalidateQueries({ queryKey: ["teams"] })
      queryClient.invalidateQueries({ queryKey: ["team", teamId] })
    },
  })
}

export function useDeleteTeam() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (teamId: number) => deleteTeam(teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teams"] })
    },
  })
}
