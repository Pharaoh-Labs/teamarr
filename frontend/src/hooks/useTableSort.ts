import { useCallback, useMemo } from "react"

import { usePersistentState } from "@/hooks/usePersistentState"

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
  /**
   * Remember the sort for the tab's lifetime under `teamarr.<persistKey>.sort`
   * (#552), so leaving for a detail page and coming back keeps it. Omit for
   * plain in-memory state.
   */
  persistKey?: string
}

interface SortState<Col extends string> {
  column: Col | null
  direction: SortDirection
}

/**
 * Column-sort state + sorted rows for tables with clickable headers.
 */
export function useTableSort<Row, Col extends string>({
  rows,
  comparators,
  cycleToNull = false,
  defaultCompare,
  persistKey,
}: UseTableSortOptions<Row, Col>) {
  const [sort, setSort] = usePersistentState<SortState<Col>>(
    persistKey ? `${persistKey}.sort` : null,
    { column: null, direction: "asc" }
  )
  const { column: sortColumn, direction: sortDirection } = sort

  const handleSort = useCallback(
    (column: Col) => {
      if (sortColumn !== column) {
        setSort({ column, direction: "asc" })
      } else if (sortDirection === "asc") {
        setSort({ column, direction: "desc" })
      } else if (cycleToNull) {
        setSort({ column: null, direction: "asc" })
      } else {
        setSort({ column, direction: "asc" })
      }
    },
    [sortColumn, sortDirection, cycleToNull, setSort]
  )

  /** Clear the column sort, returning to the default ordering. */
  const clearSort = useCallback(() => {
    setSort({ column: null, direction: "asc" })
  }, [setSort])

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
