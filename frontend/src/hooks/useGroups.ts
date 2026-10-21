import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  bulkUpdateGroups,
  clearGroupMatchCache,
  clearGroupsMatchCache,
  createGroup,
  deleteGroup,
  disableGroup,
  enableGroup,
  getGroup,
  listGroups,
  previewGroup,
  updateGroup,
} from "@/api/groups"
import type { BulkGroupUpdateRequest, EventGroupCreate, EventGroupUpdate } from "@/api/types"

export function useGroups(includeDisabled = false) {
  return useQuery({
    queryKey: ["groups", { includeDisabled }],
    queryFn: () => listGroups(includeDisabled, true),
  })
}

export function useGroup(groupId: number) {
  return useQuery({
    queryKey: ["group", groupId],
    queryFn: () => getGroup(groupId),
    enabled: groupId > 0,
  })
}

export function useCreateGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: EventGroupCreate) => createGroup(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] })
    },
  })
}

export function useUpdateGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ groupId, data }: { groupId: number; data: EventGroupUpdate }) =>
      updateGroup(groupId, data),
    onSuccess: (_, { groupId }) => {
      queryClient.invalidateQueries({ queryKey: ["groups"] })
      queryClient.invalidateQueries({ queryKey: ["group", groupId] })
    },
  })
}

export function useDeleteGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (groupId: number) => deleteGroup(groupId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] })
    },
  })
}

export function useToggleGroup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ groupId, enabled }: { groupId: number; enabled: boolean }) =>
      enabled ? enableGroup(groupId) : disableGroup(groupId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] })
    },
  })
}

export function usePreviewGroup() {
  return useMutation({
    mutationFn: (groupId: number) => previewGroup(groupId),
  })
}

export function useBulkUpdateGroups() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: BulkGroupUpdateRequest) => bulkUpdateGroups(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] })
    },
  })
}

export function useClearGroupMatchCache() {
  return useMutation({
    mutationFn: (groupId: number) => clearGroupMatchCache(groupId),
  })
}

export function useClearGroupsMatchCache() {
  return useMutation({
    mutationFn: (groupIds: number[]) => clearGroupsMatchCache(groupIds),
  })
}

