import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Trash2, Loader2, AlertTriangle } from "lucide-react"
import { Alert } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { previewResetChannels, executeResetChannels } from "@/api/channels"
import type { ResetChannelInfo } from "@/api/channels"

interface ResetAllDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** called after a successful reset (parent refreshes its channel list) */
  onReset: () => void
}

/**
 * Reset All modal — previews and deletes every Teamarr-created channel
 * (teamarr-event-* tvg_id) from Dispatcharr.
 *
 * The content mounts only while open, fetching the preview fresh each time.
 */
export function ResetAllDialog({ open, onOpenChange, onReset }: ResetAllDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <ResetAllContent onClose={() => onOpenChange(false)} onReset={onReset} />
    </Dialog>
  )
}

function ResetAllContent({
  onClose,
  onReset,
}: {
  onClose: () => void
  onReset: () => void
}) {
  const [resetLoading, setResetLoading] = useState(true)
  const [resetExecuting, setResetExecuting] = useState(false)
  const [resetChannels, setResetChannels] = useState<ResetChannelInfo[]>([])

  useEffect(() => {
    let cancelled = false
    previewResetChannels()
      .then((response) => {
        if (!cancelled) setResetChannels(response.channels)
      })
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "Failed to load reset preview")
      })
      .finally(() => {
        if (!cancelled) setResetLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleExecuteReset = async () => {
    setResetExecuting(true)
    try {
      const response = await executeResetChannels()
      if (response.success) {
        toast.success(`Deleted ${response.deleted_count} channels from Dispatcharr`)
      } else {
        toast.warning(
          `Deleted ${response.deleted_count}, failed ${response.error_count}`
        )
      }
      onReset()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reset channels")
    } finally {
      setResetExecuting(false)
    }
  }

  return (
    <DialogContent onClose={onClose} className="max-w-2xl">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="h-5 w-5" />
          Reset All Teamarr Channels
        </DialogTitle>
        <DialogDescription>
          This will delete ALL Teamarr-created channels from Dispatcharr
        </DialogDescription>
      </DialogHeader>

      <div className="py-4">
        {resetLoading ? (
          <Spinner />
        ) : resetChannels.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No Teamarr channels found in Dispatcharr.
          </div>
        ) : (
          <div className="space-y-4">
            <Alert variant="destructive" title="⚠️ Warning: Destructive Action">
              <p className="text-sm text-muted-foreground">
                This will permanently delete {resetChannels.length} channel
                {resetChannels.length > 1 ? "s" : ""} from Dispatcharr that have{" "}
                <code className="text-xs bg-muted px-1 py-0.5 rounded">teamarr-event-*</code>{" "}
                tvg_id.
              </p>
            </Alert>
            <div className="max-h-[40vh] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Channel Name</TableHead>
                    <TableHead>Channel #</TableHead>
                    <TableHead>Streams</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {resetChannels.map((ch) => (
                    <TableRow key={ch.dispatcharr_channel_id}>
                      <TableCell className="font-medium">{ch.channel_name}</TableCell>
                      <TableCell>{ch.channel_number ?? "-"}</TableCell>
                      <TableCell>{ch.stream_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        {resetChannels.length > 0 && (
          <Button
            variant="destructive"
            onClick={handleExecuteReset}
            disabled={resetExecuting}
          >
            {resetExecuting ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Trash2 className="h-4 w-4 mr-1" />
            )}
            Delete All ({resetChannels.length})
          </Button>
        )}
      </DialogFooter>
    </DialogContent>
  )
}
