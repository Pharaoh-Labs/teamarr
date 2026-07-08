import type { ReactNode } from "react"

interface StickyActionBarProps {
  /** left side, e.g. "3 teams selected" */
  label: ReactNode
  /** right side action buttons */
  children: ReactNode
}

/**
 * Fixed bottom batch-operations bar shown while table rows are selected.
 * Callers render it conditionally (`selectedIds.size > 0 && <StickyActionBar…>`).
 */
export function StickyActionBar({ label, children }: StickyActionBarProps) {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container max-w-screen-xl mx-auto px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{label}</span>
          <div className="flex items-center gap-1">{children}</div>
        </div>
      </div>
    </div>
  )
}
