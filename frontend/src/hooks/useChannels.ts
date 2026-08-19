import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  listManagedChannels,
  deleteManagedChannel,
  getReconciliationStatus,
  getPendingDeletions,
} from "@/api/channels"

export function useManagedChannels(
  groupId?: number,
  includeDeleted = false,
  opts?: { poll?: boolean }
) {
  return useQuery({
    queryKey: ["managedChannels", { groupId, includeDeleted }],
    queryFn: () => listManagedChannels(groupId, includeDeleted),
    // Poll by default; pass poll: false for secondary views (e.g. the
    // Recently Deleted list) so they refresh via invalidation only instead
    // of doubling the 30s full-table poll.
    refetchInterval: opts?.poll === false ? undefined : 30000,
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
