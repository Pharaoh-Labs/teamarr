import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createSubscriptionTemplate,
  deleteSubscriptionTemplate,
  getSubscription,
  getSubscriptionTemplates,
  updateSubscription,
  updateSubscriptionTemplate,
} from "@/api/subscription"
import type {
  SubscriptionTemplateCreate,
  SubscriptionTemplateUpdate,
  SubscriptionUpdate,
} from "@/api/subscription"

export function useSubscription() {
  return useQuery({
    queryKey: ["subscription"],
    queryFn: getSubscription,
  })
}

export function useUpdateSubscription() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: SubscriptionUpdate) => updateSubscription(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscription"] })
    },
  })
}

export function useSubscriptionTemplates() {
  return useQuery({
    queryKey: ["subscription-templates"],
    queryFn: getSubscriptionTemplates,
  })
}

export function useCreateSubscriptionTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: SubscriptionTemplateCreate) => createSubscriptionTemplate(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscription-templates"] })
      // Templates list renders per-template Usage from global_assignments
      queryClient.invalidateQueries({ queryKey: ["templates"] })
    },
  })
}

export function useUpdateSubscriptionTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      assignmentId,
      data,
    }: {
      assignmentId: number
      data: SubscriptionTemplateUpdate
    }) => updateSubscriptionTemplate(assignmentId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscription-templates"] })
      // Templates list renders per-template Usage from global_assignments
      queryClient.invalidateQueries({ queryKey: ["templates"] })
    },
  })
}

export function useDeleteSubscriptionTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (assignmentId: number) => deleteSubscriptionTemplate(assignmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subscription-templates"] })
      // Templates list renders per-template Usage from global_assignments
      queryClient.invalidateQueries({ queryKey: ["templates"] })
    },
  })
}
