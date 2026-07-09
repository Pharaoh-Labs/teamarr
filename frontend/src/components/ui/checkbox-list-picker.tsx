/**
 * CheckboxListPicker — reusable searchable multi-select checkbox list.
 *
 * Supports two modes:
 * - Flat list: pass `items` for a simple checkbox list
 * - Grouped list: pass `groups` for collapsible sport/category headers
 *
 * Inspired by LeaguePicker's visual pattern but generic enough
 * for sports, leagues, teams, or any multi-select context.
 */

import { useState, useMemo, useCallback } from "react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { SelectedBadges } from "@/components/ui/selected-badges"
import { ChevronRight, ChevronDown } from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CheckboxListItem {
  value: string
  label: string
}

export interface CheckboxListGroup {
  key: string
  label: string
  items: CheckboxListItem[]
}

interface CheckboxListPickerProps {
  /** Selected values */
  selected: string[]
  /** Selection change callback */
  onChange: (selected: string[]) => void
  /** Flat list of items (use this OR groups, not both) */
  items?: CheckboxListItem[]
  /** Grouped items with collapsible headers (use this OR items) */
  groups?: CheckboxListGroup[]
  /** Search input placeholder */
  searchPlaceholder?: string
  /** Max height CSS class for the scrollable list */
  maxHeight?: string
  /** Max badges to show before "+N more" */
  maxBadges?: number
  /** Label for the picker (optional, rendered by parent) */
  label?: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CheckboxListPicker({
  selected,
  onChange,
  items,
  groups,
  searchPlaceholder = "Search...",
  maxHeight = "max-h-48",
  maxBadges = 10,
}: CheckboxListPickerProps) {
  const [search, setSearch] = useState("")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const selectedSet = useMemo(() => new Set(selected), [selected])

  // Total item count
  const totalCount = useMemo(() => {
    if (items) return items.length
    if (groups) return groups.reduce((sum, g) => sum + g.items.length, 0)
    return 0
  }, [items, groups])

  // --- Selection helpers ---
  const toggle = useCallback((value: string) => {
    const next = new Set(selectedSet)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    onChange(Array.from(next))
  }, [selectedSet, onChange])

  const selectAll = useCallback(() => {
    if (items) {
      onChange(items.map((i) => i.value))
    } else if (groups) {
      onChange(groups.flatMap((g) => g.items.map((i) => i.value)))
    }
  }, [items, groups, onChange])

  const clearAll = useCallback(() => {
    onChange([])
  }, [onChange])

  const selectAllInGroup = useCallback((groupKey: string) => {
    const group = groups?.find((g) => g.key === groupKey)
    if (!group) return
    const next = new Set(selectedSet)
    for (const item of group.items) next.add(item.value)
    onChange(Array.from(next))
  }, [groups, selectedSet, onChange])

  const clearAllInGroup = useCallback((groupKey: string) => {
    const group = groups?.find((g) => g.key === groupKey)
    if (!group) return
    const slugs = new Set(group.items.map((i) => i.value))
    onChange(selected.filter((v) => !slugs.has(v)))
  }, [groups, selected, onChange])

  const toggleExpanded = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  // --- Lookup for badge labels ---
  const labelMap = useMemo(() => {
    const map: Record<string, string> = {}
    if (items) {
      for (const i of items) map[i.value] = i.label
    } else if (groups) {
      for (const g of groups) {
        for (const i of g.items) map[i.value] = i.label
      }
    }
    return map
  }, [items, groups])

  // --- Search filtering ---
  const lowerSearch = search.toLowerCase()

  const matchesSearch = (item: CheckboxListItem) =>
    !search ||
    item.label.toLowerCase().includes(lowerSearch) ||
    item.value.toLowerCase().includes(lowerSearch)

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-2">
      {/* Selected badges */}
      <SelectedBadges
        items={selected.map((value) => ({ key: value, label: labelMap[value] || value }))}
        maxBadges={maxBadges}
        onRemove={(key) => toggle(key)}
      />

      {/* Search input */}
      <Input
        placeholder={searchPlaceholder}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {/* Count and global actions */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {selected.length} of {totalCount} selected
        </span>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={selectAll}>
            Select All
          </Button>
          {selected.length > 0 && (
            <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={clearAll}>
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* Checkbox list */}
      <div className={cn("overflow-y-auto border rounded-md divide-y", maxHeight)}>
        {/* Flat mode */}
        {items &&
          items
            .filter(matchesSearch)
            .map((item) => {
              const isSelected = selectedSet.has(item.value)
              return (
                <label
                  key={item.value}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent text-sm",
                    isSelected && "bg-primary/10"
                  )}
                >
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => toggle(item.value)}
                  />
                  <span>{item.label}</span>
                </label>
              )
            })}

        {/* Grouped mode */}
        {groups &&
          groups
            .filter((group) =>
              !search ||
              group.label.toLowerCase().includes(lowerSearch) ||
              group.items.some(matchesSearch)
            )
            .map((group) => {
              const filtered = search
                ? group.items.filter(matchesSearch)
                : group.items

              // If group label matches but no items do, show all items
              const display =
                search &&
                filtered.length === 0 &&
                group.label.toLowerCase().includes(lowerSearch)
                  ? group.items
                  : filtered

              if (display.length === 0) return null

              const groupSelectedCount = display.filter((i) => selectedSet.has(i.value)).length
              const allGroupSelected = groupSelectedCount === display.length

              // Single group: no collapsible header needed
              if (groups.length === 1) {
                return (
                  <div key={group.key} className="divide-y">
                    {display.map((item) => {
                      const isSelected = selectedSet.has(item.value)
                      return (
                        <label
                          key={item.value}
                          className={cn(
                            "flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent text-sm",
                            isSelected && "bg-primary/10"
                          )}
                        >
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggle(item.value)}
                          />
                          <span className="truncate">{item.label}</span>
                        </label>
                      )
                    })}
                  </div>
                )
              }

              // Multi-group: collapsible headers
              const isExpanded = expanded.has(group.key) || !!search

              return (
                <div key={group.key}>
                  <div
                    className="flex items-center justify-between px-3 py-2 bg-muted/50 sticky top-0 cursor-pointer hover:bg-muted/70"
                    onClick={() => toggleExpanded(group.key)}
                  >
                    <div className="flex items-center gap-2">
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                      <span className="font-medium text-sm">
                        {group.label} ({display.length})
                      </span>
                      {groupSelectedCount > 0 && !isExpanded && (
                        <Badge variant="secondary" className="text-xs h-5">
                          {groupSelectedCount} selected
                        </Badge>
                      )}
                    </div>
                    {isExpanded && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (allGroupSelected) {
                            clearAllInGroup(group.key)
                          } else {
                            selectAllInGroup(group.key)
                          }
                        }}
                      >
                        {allGroupSelected ? "Clear" : "Select All"}
                      </Button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="divide-y">
                      {display.map((item) => {
                        const isSelected = selectedSet.has(item.value)
                        return (
                          <label
                            key={item.value}
                            className={cn(
                              "flex items-center gap-3 px-3 py-2 pl-9 cursor-pointer hover:bg-accent text-sm",
                              isSelected && "bg-primary/10"
                            )}
                          >
                            <Checkbox
                              checked={isSelected}
                              onCheckedChange={() => toggle(item.value)}
                            />
                            <span className="truncate">{item.label}</span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
      </div>
    </div>
  )
}
