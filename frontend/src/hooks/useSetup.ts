import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { dismissGettingStarted, getSetupStatus, restoreGettingStarted } from "@/api/setup"

export function useSetupStatus() {
  return useQuery({
    queryKey: ["setup", "status"],
    queryFn: getSetupStatus,
    refetchInterval: 30000,
  })
}

function useSetupMutation(fn: () => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["setup"] })
      queryClient.invalidateQueries({ queryKey: ["settings", "display"] })
    },
  })
}

export const useDismissGettingStarted = () => useSetupMutation(dismissGettingStarted)
export const useRestoreGettingStarted = () => useSetupMutation(restoreGettingStarted)
