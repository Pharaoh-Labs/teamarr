import { type ReactNode } from "react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

export interface ResponsiveColumn<T> {
  /** Stable key for the column. */
  key: string
  /** Header label (also the default mobile field label). */
  header: ReactNode
  /** Renders the cell value for a row — JSX is fine (badges, buttons, tooltips). */
  cell: (row: T) => ReactNode
  align?: "left" | "center" | "right"
  headerClassName?: string
  cellClassName?: string
  /** Render in the mobile card's title row instead of the label/value list. */
  mobileTitle?: boolean
  /** Omit this column from the mobile card. */
  mobileHidden?: boolean
  /** Label before the value in the mobile card (defaults to `header`). */
  mobileLabel?: ReactNode
}

interface ResponsiveTableProps<T> {
  rows: T[]
  columns: ResponsiveColumn<T>[]
  keyExtractor: (row: T, index: number) => string | number
  onRowClick?: (row: T) => void
  /** Extra classes per row/card (e.g. dim disabled rows). */
  rowClassName?: (row: T) => string | undefined
  /** Escape hatch: fully custom mobile card for a row (overrides the default). */
  renderMobileCard?: (row: T) => ReactNode
  emptyMessage?: ReactNode
  className?: string
  cardClassName?: string
}

const alignClass = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
} as const

/**
 * The single responsive data-table primitive: one column config drives BOTH a
 * full table (≥ sm) and a stacked card list (< sm), so the two layouts can't
 * drift. `mobileTitle` columns become the card heading; `mobileHidden` columns
 * drop on phones; everything else renders as a label/value row. Pass
 * `renderMobileCard` to hand-tune a specific table's phone layout.
 */
export function ResponsiveTable<T>({
  rows,
  columns,
  keyExtractor,
  onRowClick,
  rowClassName,
  renderMobileCard,
  emptyMessage,
  className,
  cardClassName,
}: ResponsiveTableProps<T>) {
  if (rows.length === 0 && emptyMessage) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{emptyMessage}</div>
  }

  const titleCols = columns.filter((c) => c.mobileTitle)
  const bodyCols = columns.filter((c) => !c.mobileTitle && !c.mobileHidden)

  return (
    <>
      {/* Desktop: full table */}
      <div className={cn("hidden sm:block", className)}>
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c.key} className={cn(c.align && alignClass[c.align], c.headerClassName)}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, i) => (
              <TableRow
                key={keyExtractor(row, i)}
                className={cn(onRowClick && "cursor-pointer", rowClassName?.(row))}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((c) => (
                  <TableCell key={c.key} className={cn(c.align && alignClass[c.align], c.cellClassName)}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Mobile: stacked cards */}
      <div className="space-y-2 sm:hidden">
        {rows.map((row, i) =>
          renderMobileCard ? (
            <div key={keyExtractor(row, i)}>{renderMobileCard(row)}</div>
          ) : (
            <div
              key={keyExtractor(row, i)}
              className={cn(
                "rounded-lg border bg-card p-3 space-y-2",
                onRowClick && "cursor-pointer",
                cardClassName,
                rowClassName?.(row),
              )}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {titleCols.length > 0 && (
                <div className="flex items-center justify-between gap-2 font-medium">
                  {titleCols.map((c) => (
                    <span key={c.key} className="flex items-center gap-2">
                      {c.cell(row)}
                    </span>
                  ))}
                </div>
              )}
              {bodyCols.length > 0 && (
                <div className="space-y-1 text-sm">
                  {bodyCols.map((c) => (
                    <div key={c.key} className="flex items-center justify-between gap-3">
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {c.mobileLabel ?? c.header}
                      </span>
                      <span className="text-right">{c.cell(row)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ),
        )}
      </div>
    </>
  )
}
