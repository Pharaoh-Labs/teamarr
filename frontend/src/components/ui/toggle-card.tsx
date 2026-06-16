import { type ReactNode } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

interface ToggleCardProps {
  /** Card heading. */
  title: ReactNode
  /** Optional muted subtitle under the title (always visible). */
  description?: ReactNode
  /** Master toggle state. */
  enabled: boolean
  /** Master toggle handler. */
  onEnabledChange: (enabled: boolean) => void
  /** Rendered in the header to the LEFT of the toggle (e.g. a status badge). */
  headerExtra?: ReactNode
  /** Disable the master toggle. */
  disabled?: boolean
  /** Body content shown regardless of the toggle (e.g. a status row). */
  always?: ReactNode
  /** Body content revealed only when enabled — the gated sub-options. */
  children?: ReactNode
  /** Body content shown regardless of the toggle, below children (e.g. Save). */
  footer?: ReactNode
  className?: string
  contentClassName?: string
}

/**
 * The single app-wide "optional section" card: a Card whose master toggle sits
 * in the header upper-right and gates the rest of the card. When off, only the
 * header (plus any `always`/`footer` content) shows; when on, the sub-options
 * in `children` are revealed. Replaces the hand-rolled header-toggle pattern
 * (Provider EPG Backup, Feed Separation, Update Notifications, …).
 */
export function ToggleCard({
  title,
  description,
  enabled,
  onEnabledChange,
  headerExtra,
  disabled,
  always,
  children,
  footer,
  className,
  contentClassName,
}: ToggleCardProps) {
  const hasBody = always != null || (enabled && children != null) || footer != null

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {headerExtra}
            <Switch checked={enabled} onCheckedChange={onEnabledChange} disabled={disabled} />
          </div>
        </div>
      </CardHeader>
      {hasBody && (
        <CardContent className={cn("space-y-4", contentClassName)}>
          {always}
          {enabled && children}
          {footer}
        </CardContent>
      )}
    </Card>
  )
}
