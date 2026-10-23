import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  type ManualEventInput,
  cancelManualEvent,
  createManualEvent,
  listManualEvents,
  updateManualEvent,
} from "@/api/manualEvents"

export function useManualEvents() {
  return useQuery({
    queryKey: ["manual-events"],
    queryFn: listManualEvents,
  })
}

export function useCreateManualEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ManualEventInput) => createManualEvent(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["manual-events"] }),
  })
}

export function useUpdateManualEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ eventId, data }: { eventId: string; data: ManualEventInput }) =>
      updateManualEvent(eventId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["manual-events"] }),
  })
}

export function useCancelManualEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ eventId, league }: { eventId: string; league: string }) =>
      cancelManualEvent(eventId, league),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["manual-events"] }),
  })
}
