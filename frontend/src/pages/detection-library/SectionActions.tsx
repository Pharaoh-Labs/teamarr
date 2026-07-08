import { Plus, Loader2, Upload, Download } from "lucide-react"
import { Button } from "@/components/ui/button"

interface SectionActionsProps {
  addLabel: string
  onAdd: () => void
  onImport: () => void
  onExport: () => void
  isImporting: boolean
}

/** Add / Import / Export button trio for a Detection Library section header. */
export function SectionActions({
  addLabel,
  onAdd,
  onImport,
  onExport,
  isImporting,
}: SectionActionsProps) {
  return (
    <>
      <Button size="sm" onClick={onAdd}>
        <Plus className="h-4 w-4 mr-1" />
        {addLabel}
      </Button>
      <Button variant="outline" size="sm" onClick={onImport} disabled={isImporting} title="Import">
        {isImporting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Upload className="h-4 w-4" />
        )}
      </Button>
      <Button variant="outline" size="sm" onClick={onExport} title="Export">
        <Download className="h-4 w-4" />
      </Button>
    </>
  )
}
