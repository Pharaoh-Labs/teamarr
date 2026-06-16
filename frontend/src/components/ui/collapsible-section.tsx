import { type ReactNode } from "react"
import { ChevronRight, ChevronDown } from "lucide-react"
import { usePersistentCollapse } from "@/hooks/usePersistentCollapse"
import { cn } from "@/lib/utils"

interface CollapsibleSectionProps {
  /** Header label. */
  title: ReactNode
  /** Optional leading icon, rendered between the chevron and the title. */
  icon?: ReactNode
  /** Optional muted count/badge rendered after the title (e.g. "(50)"). */
  count?: ReactNode
  /** Optional right-side controls (buttons, etc). Rendered as siblings of the
   *  toggle — never nested inside it — so clicking them never toggles. */
  actions?: ReactNode
  /** "section" (default, prominent) or "subsection" (lighter, for nesting). */
  variant?: "section" | "subsection"
  /** If set, collapse state persists across visits under this key. */
  persistKey?: string
  defaultCollapsed?: boolean
  /** Extra classes for the outer wrapper. */
  className?: string
  children: ReactNode
}

/**
 * The single app-wide collapsible-section primitive (epic wk7t). Variant 1:
 * a minimal header row — left chevron + optional icon + bold label + optional
 * count, with optional right-side actions — over a thin divider, body below.
 * Low chrome so it nests cleanly inside cards and stands alone at top level.
 *
 * Use ONLY for disclosing a content section. Dropdown/picker chevrons are a
 * different concept and are not this component.
 */
export function CollapsibleSection({
  title,
  icon,
  count,
  actions,
  variant = "section",
  persistKey,
  defaultCollapsed = true,
  className,
  children,
}: CollapsibleSectionProps) {
  const [collapsed, setCollapsed] = usePersistentCollapse(persistKey, defaultCollapsed)
  const Chevron = collapsed ? ChevronRight : ChevronDown

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between gap-2 border-b pb-2">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex min-w-0 cursor-pointer items-center gap-2 text-left hover:opacity-80"
        >
          <Chevron className="h-4 w-4 shrink-0 text-muted-foreground" />
          {icon}
          <span
            className={cn(
              "truncate",
              variant === "subsection" ? "text-sm font-medium" : "text-lg font-semibold",
            )}
          >
            {title}
          </span>
          {count != null && (
            <span className="shrink-0 text-sm font-normal text-muted-foreground">{count}</span>
          )}
        </button>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {!collapsed && <div>{children}</div>}
    </div>
  )
}
