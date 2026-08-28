import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getNumberingExceptions,
  createNumberingException,
  updateNumberingException,
  deleteNumberingException,
  reorderNumberingExceptions,
  getNumberingPreview,
} from "@/api/numberingExceptions"
import type {
  NumberingExceptionCreate,
  NumberingExceptionUpdate,
} from "@/api/numberingExceptions"

const KEY = ["numbering-exceptions"]
const PREVIEW_KEY = ["numbering-exceptions", "preview"]

function useInvalidate() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: KEY })
    // Block edits arm a re-grid — the numbering settings blob carries that flag.
    qc.invalidateQueries({ queryKey: ["settings", "channel-numbering"] })
  }
}

export function useNumberingExceptions() {
  return useQuery({ queryKey: KEY, queryFn: getNumberingExceptions })
}

export function useNumberingPreview() {
  return useQuery({ queryKey: PREVIEW_KEY, queryFn: getNumberingPreview })
}

export function useCreateNumberingException() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (data: NumberingExceptionCreate) => createNumberingException(data),
    onSuccess: invalidate,
  })
}

export function useUpdateNumberingException() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: NumberingExceptionUpdate }) =>
      updateNumberingException(id, data),
    onSuccess: invalidate,
  })
}

export function useDeleteNumberingException() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => deleteNumberingException(id),
    onSuccess: invalidate,
  })
}

export function useReorderNumberingExceptions() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (ids: number[]) => reorderNumberingExceptions(ids),
    onSuccess: invalidate,
  })
}
