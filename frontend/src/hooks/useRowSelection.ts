import { useCallback, useState } from "react"

/**
 * Multi-select state for table rows keyed by numeric id, with optional
 * shift-click range selection.
 *
 * `toggle(id)` is a plain toggle. Pass `index` and `shiftKey` from the click
 * handler to enable range selection: shift-clicking adds every row between the
 * last clicked row and this one (both from the CURRENT `rows` order, so pass
 * the same filtered/sorted array the table renders).
 */
export function useRowSelection<Row extends { id: number }>(rows: Row[]) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [lastClickedIndex, setLastClickedIndex] = useState<number | null>(null)

  const toggle = useCallback(
    (id: number, index?: number, shiftKey?: boolean) => {
      if (shiftKey && index !== undefined && lastClickedIndex !== null) {
        const start = Math.min(lastClickedIndex, index)
        const end = Math.max(lastClickedIndex, index)
        setSelectedIds((prev) => {
          const next = new Set(prev)
          for (let i = start; i <= end; i++) {
            const row = rows[i]
            if (row) next.add(row.id)
          }
          return next
        })
      } else {
        setSelectedIds((prev) => {
          const next = new Set(prev)
          if (next.has(id)) {
            next.delete(id)
          } else {
            next.add(id)
          }
          return next
        })
      }
      if (index !== undefined) setLastClickedIndex(index)
    },
    [rows, lastClickedIndex]
  )

  const toggleAll = useCallback(() => {
    if (rows.length === 0) return
    setSelectedIds((prev) =>
      prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id))
    )
  }, [rows])

  const clear = useCallback(() => {
    setSelectedIds(new Set())
    setLastClickedIndex(null)
  }, [])

  const isAllSelected = rows.length > 0 && selectedIds.size === rows.length

  return { selectedIds, toggle, toggleAll, clear, isAllSelected, setSelectedIds }
}
