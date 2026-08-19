import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Multi-select state for table rows keyed by numeric id, with optional
 * shift-click range selection.
 *
 * `toggle(id)` is a plain toggle. Pass `index` and `shiftKey` from the click
 * handler to enable range selection: shift-clicking adds every row between the
 * last clicked row and this one (both from the CURRENT `rows` order, so pass
 * the same filtered/sorted array the table renders).
 *
 * `toggle` and `toggleAll` have stable identities (rows and the range anchor
 * live in refs), so they can be passed to React.memo'd rows without defeating
 * the memo.
 */
export function useRowSelection<Row extends { id: number }>(rows: Row[]) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const rowsRef = useRef(rows)
  // Latest-ref pattern, updated post-commit: toggle/toggleAll only read it
  // from event handlers, which always fire after the effect has run.
  useEffect(() => {
    rowsRef.current = rows
  }, [rows])
  // Range anchor. A ref, not state: it never needs to trigger a render.
  const lastClickedIndexRef = useRef<number | null>(null)

  const toggle = useCallback((id: number, index?: number, shiftKey?: boolean) => {
    const lastClickedIndex = lastClickedIndexRef.current
    if (shiftKey && index !== undefined && lastClickedIndex !== null) {
      const start = Math.min(lastClickedIndex, index)
      const end = Math.max(lastClickedIndex, index)
      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (let i = start; i <= end; i++) {
          const row = rowsRef.current[i]
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
    if (index !== undefined) lastClickedIndexRef.current = index
  }, [])

  const toggleAll = useCallback(() => {
    const current = rowsRef.current
    if (current.length === 0) return
    setSelectedIds((prev) =>
      prev.size === current.length ? new Set() : new Set(current.map((r) => r.id))
    )
  }, [])

  const clear = useCallback(() => {
    setSelectedIds(new Set())
    lastClickedIndexRef.current = null
  }, [])

  const isAllSelected = rows.length > 0 && selectedIds.size === rows.length

  return { selectedIds, toggle, toggleAll, clear, isAllSelected, setSelectedIds }
}
