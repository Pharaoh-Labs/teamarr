import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  arrangeSources,
  clearSourceFolders,
  createSourceFolder,
  deleteSourceFolder,
  listSourceFolders,
  putArrangement,
  undoArrangement,
  updateSourceFolder,
  type ArrangeBy,
  type FolderPlacement,
  type SourcePlacement,
} from "@/api/sourceFolders"

const KEY = ["source-folders"]

export function useSourceFolders() {
  return useQuery({ queryKey: KEY, queryFn: listSourceFolders })
}

function useArrangementMutation<Args, Result>(fn: (args: Args) => Promise<Result>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      // Folder rows and each source's folder_id/sort_order both change.
      queryClient.invalidateQueries({ queryKey: KEY })
      queryClient.invalidateQueries({ queryKey: ["groups"] })
    },
  })
}

export function useCreateSourceFolder() {
  return useArrangementMutation((name: string) => createSourceFolder(name))
}

export function useUpdateSourceFolder() {
  return useArrangementMutation(
    ({ folderId, ...data }: { folderId: number; name?: string; collapsed?: boolean }) =>
      updateSourceFolder(folderId, data)
  )
}

export function useDeleteSourceFolder() {
  return useArrangementMutation((folderId: number) => deleteSourceFolder(folderId))
}

export function usePutArrangement() {
  return useArrangementMutation(
    ({ sources, folders }: { sources: SourcePlacement[]; folders?: FolderPlacement[] }) =>
      putArrangement(sources, folders)
  )
}

export function useArrangeSources() {
  return useArrangementMutation((by: ArrangeBy) => arrangeSources(by))
}

export function useUndoArrangement() {
  return useArrangementMutation(() => undoArrangement())
}

export function useClearSourceFolders() {
  return useArrangementMutation(() => clearSourceFolders())
}
