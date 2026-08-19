import { useCallback, useMemo, useState } from "react"

export type SortDirection = "asc" | "desc"

interface UseTableSortOptions<Row, Col extends string> {
  /** Already-filtered rows; the hook only sorts. */
  rows: Row[]
  /** Ascending comparator per sortable column. */
  comparators: Record<Col, (a: Row, b: Row) => number>
  /**
   * Third click on the same column clears the sort (asc → desc → none).
   * Default false: asc ↔ desc toggle.
   */
  cycleToNull?: boolean
  /**
   * Ordering applied while no column is sorted (e.g. a persisted sort_order
   * field). Omit to keep the input order.
   */
  defaultCompare?: (a: Row, b: Row) => number
}

/**
 * Column-sort state + sorted rows for tables with clickable headers.
 */
export function useTableSort<Row, Col extends string>({
  rows,
  comparators,
  cycleToNull = false,
  defaultCompare,
}: UseTableSortOptions<Row, Col>) {
  const [sortColumn, setSortColumn] = useState<Col | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc")

  const handleSort = useCallback(
    (column: Col) => {
      if (sortColumn !== column) {
        setSortColumn(column)
        setSortDirection("asc")
      } else if (sortDirection === "asc") {
        setSortDirection("desc")
      } else if (cycleToNull) {
        setSortColumn(null)
        setSortDirection("asc")
      } else {
        setSortDirection("asc")
      }
    },
    [sortColumn, sortDirection, cycleToNull]
  )

  /** Clear the column sort, returning to the default ordering. */
  const clearSort = useCallback(() => {
    setSortColumn(null)
    setSortDirection("asc")
  }, [])

  const sortedRows = useMemo(() => {
    const result = [...rows]
    if (sortColumn === null) {
      if (defaultCompare) result.sort(defaultCompare)
      return result
    }
    const compare = comparators[sortColumn]
    result.sort((a, b) => {
      const cmp = compare(a, b)
      return sortDirection === "asc" ? cmp : -cmp
    })
    return result
    // comparators is expected to be a stable module-level map or memoized
  }, [rows, sortColumn, sortDirection, comparators, defaultCompare])

  return { sortColumn, sortDirection, handleSort, clearSort, sortedRows }
}
