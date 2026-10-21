import { api } from "./client"
import type { SourceFolder } from "./types"

export interface SourceFolderListResponse {
  folders: SourceFolder[]
  can_undo: boolean
}

export interface SourcePlacement {
  group_id: number
  folder_id: number | null
  sort_order: number
}

export interface FolderPlacement {
  folder_id: number
  sort_order: number
}

export interface ArrangeResponse {
  folders: number
  filed: number
  unfiled: number
  can_undo: boolean
}

export type ArrangeBy = "provider" | "sport" | "league"

export async function listSourceFolders(): Promise<SourceFolderListResponse> {
  return api.get("/source-folders")
}

export async function createSourceFolder(name: string): Promise<SourceFolder> {
  return api.post("/source-folders", { name })
}

export async function updateSourceFolder(
  folderId: number,
  data: { name?: string; collapsed?: boolean }
): Promise<SourceFolder> {
  return api.patch(`/source-folders/${folderId}`, data)
}

export async function deleteSourceFolder(folderId: number): Promise<void> {
  return api.delete(`/source-folders/${folderId}`)
}

export async function putArrangement(
  sources: SourcePlacement[],
  folders: FolderPlacement[] = []
): Promise<{ updated: number }> {
  return api.put("/source-folders/arrangement", { sources, folders })
}

export async function arrangeSources(by: ArrangeBy): Promise<ArrangeResponse> {
  return api.post("/source-folders/arrange", { by })
}

export async function undoArrangement(): Promise<SourceFolderListResponse> {
  return api.post("/source-folders/undo", {})
}

export async function clearSourceFolders(): Promise<SourceFolderListResponse> {
  return api.post("/source-folders/clear", {})
}
