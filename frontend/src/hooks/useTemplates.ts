import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { listTemplates, createTemplate, deleteTemplate } from "@/api/templates"
import type { TemplateCreate } from "@/api/templates"

export function useTemplates() {
  return useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
  })
}

export function useCreateTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: TemplateCreate) => createTemplate(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] })
    },
  })
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (templateId: number) => deleteTemplate(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] })
    },
  })
}
