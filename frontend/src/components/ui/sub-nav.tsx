import { type ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"

export interface SubNavItem {
  /** Stable key (also the value in state mode). */
  key: string
  label: string
  /** Route mode: render a NavLink to this path. Omit for state mode. */
  to?: string
  end?: boolean
  /** Optional leading icon. */
  icon?: ReactNode
  disabled?: boolean
  /** Tooltip (e.g. why an item is disabled). */
  title?: string
}

interface SubNavProps {
  items: SubNavItem[]
  /** State mode: the active item's key. */
  value?: string
  /** State mode: called with the clicked item's key. */
  onChange?: (key: string) => void
  className?: string
}

const TRACK = "inline-flex flex-wrap items-center gap-1 rounded-lg bg-muted p-1"
const ITEM = "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors cursor-pointer"
const ACTIVE = "bg-background text-foreground shadow-sm"
const INACTIVE = "text-muted-foreground hover:text-foreground"
const DISABLED = "opacity-50 cursor-not-allowed"

/**
 * The single app-wide secondary-navigation primitive (epic j35s): a refined
 * segmented control — a muted track with the active segment raised/filled. Kept
 * lighter than the top-level main nav so the hierarchy reads (main nav > sub
 * nav). Use ONLY for within-tab section switching.
 *
 * Two modes (don't mix within one SubNav):
 *  - State: pass `value` + `onChange`; items use `key`.
 *  - Route: give items a `to`; renders NavLinks with router-driven active state.
 */
export function SubNav({ items, value, onChange, className }: SubNavProps) {
  const routeMode = items.some((i) => i.to)

  return (
    <div className={cn(TRACK, className)}>
      {items.map((item) => {
        const content = (
          <>
            {item.icon}
            {item.label}
          </>
        )

        if (item.disabled) {
          return (
            <span key={item.key} title={item.title} className={cn(ITEM, INACTIVE, DISABLED)}>
              {content}
            </span>
          )
        }

        if (routeMode && item.to) {
          return (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.end}
              title={item.title}
              className={({ isActive }) => cn(ITEM, isActive ? ACTIVE : INACTIVE)}
            >
              {content}
            </NavLink>
          )
        }

        return (
          <button
            key={item.key}
            type="button"
            title={item.title}
            onClick={() => onChange?.(item.key)}
            className={cn(ITEM, value === item.key ? ACTIVE : INACTIVE)}
          >
            {content}
          </button>
        )
      })}
    </div>
  )
}
