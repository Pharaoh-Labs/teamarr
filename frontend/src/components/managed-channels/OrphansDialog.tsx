import { useMemo, useState } from "react"
import { toast } from "sonner"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2, Loader2, RefreshCw, AlertTriangle } from "lucide-react"
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
import { useReconciliationStatus } from "@/hooks/useChannels"
import { deleteDispatcharrChannel } from "@/api/channels"

interface OrphansDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Find Orphans modal — lists Dispatcharr channels not tracked by Teamarr and
 * lets the user delete them one-by-one or all at once.
 *
 * The content (and its reconciliation query) mounts only while the dialog is
 * open, so the status is fetched fresh on each open.
 */
export function OrphansDialog({ open, onOpenChange }: OrphansDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <OrphansContent onClose={() => onOpenChange(false)} />
    </Dialog>
  )
}

function OrphansContent({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [deletingOrphanId, setDeletingOrphanId] = useState<number | null>(null)
  const [deletingAllOrphans, setDeletingAllOrphans] = useState(false)

  const {
    data: reconciliationData,
    isLoading: reconciliationLoading,
    refetch: refetchReconciliation,
  } = useReconciliationStatus()

  // Filter orphan_dispatcharr issues
  const orphanChannels = useMemo(() => {
    if (!reconciliationData?.issues_found) return []
    return reconciliationData.issues_found.filter(
      (issue) => issue.issue_type === "orphan_dispatcharr"
    )
  }, [reconciliationData])

  const deleteOrphanMutation = useMutation({
    mutationFn: deleteDispatcharrChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] })
      refetchReconciliation()
    },
  })

  const handleDeleteOrphan = async (channelId: number) => {
    setDeletingOrphanId(channelId)
    try {
      await deleteOrphanMutation.mutateAsync(channelId)
      toast.success("Orphan channel deleted from Dispatcharr")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete orphan")
    } finally {
      setDeletingOrphanId(null)
    }
  }

  const handleDeleteAllOrphans = async () => {
    const channelIds = orphanChannels
      .map((o) => o.dispatcharr_channel_id)
      .filter((id): id is number => id !== null && id !== undefined)

    if (channelIds.length === 0) return

    setDeletingAllOrphans(true)
    try {
      const results = await Promise.allSettled(
        channelIds.map((id) => deleteOrphanMutation.mutateAsync(id))
      )
      const succeeded = results.filter((r) => r.status === "fulfilled").length
      const failed = results.filter((r) => r.status === "rejected").length

      if (failed === 0) {
        toast.success(`Deleted ${succeeded} orphan channels`)
      } else {
        toast.warning(`Deleted ${succeeded}, failed ${failed}`)
      }
      refetchReconciliation()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete orphans")
    } finally {
      setDeletingAllOrphans(false)
    }
  }

  return (
    <DialogContent onClose={onClose} className="max-w-2xl">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-warning" />
          Orphan Channels
        </DialogTitle>
        <DialogDescription>
          Channels in Dispatcharr that aren't tracked by Teamarr
        </DialogDescription>
      </DialogHeader>

      <div className="py-4">
        {reconciliationLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : orphanChannels.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No orphan channels found. Everything is in sync!
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Found {orphanChannels.length} orphan channel
              {orphanChannels.length > 1 ? "s" : ""}. These exist in Dispatcharr but
              aren't tracked by Teamarr.
            </p>
            <div className="max-h-[50vh] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel Name</TableHead>
                  <TableHead>Dispatcharr ID</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orphanChannels.map((orphan, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">
                      {orphan.channel_name ?? "Unknown"}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {orphan.dispatcharr_channel_id}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() =>
                          orphan.dispatcharr_channel_id &&
                          handleDeleteOrphan(orphan.dispatcharr_channel_id)
                        }
                        disabled={
                          !orphan.dispatcharr_channel_id ||
                          deletingOrphanId === orphan.dispatcharr_channel_id
                        }
                      >
                        {deletingOrphanId === orphan.dispatcharr_channel_id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </Button>
                    </TableCell>
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
          Close
        </Button>
        <Button
          variant="outline"
          onClick={() => refetchReconciliation()}
          disabled={reconciliationLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${reconciliationLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        {orphanChannels.length > 0 && (
          <Button
            variant="destructive"
            onClick={handleDeleteAllOrphans}
            disabled={deletingAllOrphans}
          >
            {deletingAllOrphans ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Trash2 className="h-4 w-4 mr-1" />
            )}
            Delete All ({orphanChannels.length})
          </Button>
        )}
      </DialogFooter>
    </DialogContent>
  )
}
