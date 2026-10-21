import { useEffect, useRef, useState } from "react"
import { ChevronDown, FolderPlus, Layers, Undo2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { ArrangeBy } from "@/api/sourceFolders"
import {
  useArrangeSources,
  useClearSourceFolders,
  useCreateSourceFolder,
  useUndoArrangement,
} from "@/hooks/useSourceFolders"

interface ArrangeMenuProps {
  folderCount: number
  canUndo: boolean
}

/**
 * The Sources page arrangement actions (#1110): new folder, the one-time
 * auto-arrange actions (by provider, sport or league), Undo and Remove all
 * folders. Arrangement is cosmetic (#1109) — none of this touches matching
 * or stream priority — so nothing here asks for confirmation; Undo is the
 * safety net.
 */
export function ArrangeMenu({ folderCount, canUndo }: ArrangeMenuProps) {
  const [open, setOpen] = useState(false)
  const [newFolderOpen, setNewFolderOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState("")
  const ref = useRef<HTMLDivElement>(null)
  const createMutation = useCreateSourceFolder()
  const arrangeMutation = useArrangeSources()
  const undoMutation = useUndoArrangement()
  const clearMutation = useClearSourceFolders()

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  const busy =
    createMutation.isPending ||
    arrangeMutation.isPending ||
    undoMutation.isPending ||
    clearMutation.isPending

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setOpen(false)
    try {
      await fn()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to ${label}`)
    }
  }

  const arrange = (by: ArrangeBy) =>
    run(`arrange by ${by}`, async () => {
      const result = await arrangeMutation.mutateAsync(by)
      const unfiled = result.unfiled > 0 ? `, ${result.unfiled} with no matches left at the top level` : ""
      toast.success(`${result.filed} sources filed into ${result.folders} folders${unfiled}`)
    })

  const createFolder = async () => {
    const name = newFolderName.trim()
    if (!name) return
    try {
      await createMutation.mutateAsync(name)
      setNewFolderName("")
      setNewFolderOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create folder")
    }
  }

  const item = (label: string, onClick: () => void, opts: { disabled?: boolean; icon?: React.ReactNode; hint?: string } = {}) => (
    <button
      type="button"
      className="w-full text-left px-2.5 py-1.5 text-sm flex items-center gap-2 hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
      onClick={onClick}
      disabled={opts.disabled || busy}
      title={opts.hint}
    >
      {opts.icon}
      {label}
    </button>
  )

  return (
    <div ref={ref} className="relative">
      <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} title="Arrange the list into folders. Arrangement never affects matching or stream priority.">
        <Layers className="h-4 w-4 mr-1" />
        Arrange
        <ChevronDown className="h-3 w-3 ml-1" />
      </Button>
      {open && (
        <div className="absolute right-0 mt-1 w-64 rounded-md border border-border bg-popover shadow-md z-20 py-1">
          {item("New folder…", () => { setOpen(false); setNewFolderOpen(true) }, { icon: <FolderPlus className="h-4 w-4" /> })}
          <div className="px-2.5 pt-2 pb-1 text-[0.65rem] uppercase tracking-wide text-muted-foreground">Group into folders</div>
          {item("By provider", () => arrange("provider"), { hint: "One folder per M3U account" })}
          {item("By sport", () => arrange("sport"), { hint: "By what each source matched in the last run; mixed sources go under Multi" })}
          {item("By league", () => arrange("league"), { hint: "By what each source matched in the last run; mixed sources go under Multi" })}
          <div className="my-1 border-t border-border" />
          {item("Undo last arrange", () => run("undo", () => undoMutation.mutateAsync()), { disabled: !canUndo, icon: <Undo2 className="h-4 w-4" /> })}
          {item("Remove all folders", () => run("remove folders", () => clearMutation.mutateAsync()), { disabled: folderCount === 0, icon: <X className="h-4 w-4" />, hint: "Sources keep their order at the top level" })}
        </div>
      )}

      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>New folder</DialogTitle>
            <DialogDescription>Drag sources into it, or select them and use Move to folder.</DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            placeholder="Folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void createFolder() }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewFolderOpen(false)}>Cancel</Button>
            <Button onClick={createFolder} disabled={!newFolderName.trim() || createMutation.isPending}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
