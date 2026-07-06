import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { fetchPresets, createPreset, deletePreset } from "@/api/presets"
import type { ConditionPresetCreate } from "@/api/presets"

export function usePresets() {
  return useQuery({
    queryKey: ["presets"],
    queryFn: fetchPresets,
    select: (data) => data.presets,
  })
}

export function useCreatePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: ConditionPresetCreate) => createPreset(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["presets"] })
    },
  })
}

export function useDeletePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (presetId: number) => deletePreset(presetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["presets"] })
    },
  })
}
