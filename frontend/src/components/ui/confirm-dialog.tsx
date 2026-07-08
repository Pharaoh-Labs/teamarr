import type { ReactNode } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "./button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "./dialog"

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  /** ReactNode so callers can interpolate names/counts with markup */
  description: ReactNode
  confirmLabel: ReactNode
  confirmVariant?: "destructive" | "default"
  /** Disables the confirm button and shows a spinner while the mutation runs */
  isPending?: boolean
  onConfirm: () => void
}

/**
 * Confirmation modal for destructive/irreversible actions.
 *
 * Replaces the hand-rolled Dialog + Cancel/destructive-Button pattern that was
 * duplicated across Teams, EventGroups, ManagedChannelsTable, and
 * DetectionLibrary.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  confirmVariant = "destructive",
  isPending = false,
  onConfirm,
}: ConfirmDialogProps) {
  const close = () => onOpenChange(false)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent onClose={close}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} disabled={isPending}>
            {isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
