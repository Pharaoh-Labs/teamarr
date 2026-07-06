import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  listManagedChannels,
  deleteManagedChannel,
  getReconciliationStatus,
  getPendingDeletions,
} from "@/api/channels"

export function useManagedChannels(groupId?: number, includeDeleted = false) {
  return useQuery({
    queryKey: ["managedChannels", { groupId, includeDeleted }],
    queryFn: () => listManagedChannels(groupId, includeDeleted),
    refetchInterval: 30000, // Refresh every 30s
  })
}

export function useDeleteManagedChannel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (channelId: number) => deleteManagedChannel(channelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["managedChannels"] })
    },
  })
}

export function useReconciliationStatus() {
  return useQuery({
    queryKey: ["reconciliationStatus"],
    queryFn: () => getReconciliationStatus(),
  })
}

export function usePendingDeletions() {
  return useQuery({
    queryKey: ["pendingDeletions"],
    queryFn: getPendingDeletions,
    refetchInterval: 60000, // Check every minute
  })
}
