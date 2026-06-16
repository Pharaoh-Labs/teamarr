import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * Alert — a tinted callout/banner with a semantic tone. Replaces the many
 * hand-rolled colored boxes across the app (info "What is X" tiles, success /
 * warning status boxes, destructive error banners). Pass an optional `icon`
 * and `title`; body goes in children.
 */
const alertVariants = cva(
  "flex gap-2.5 rounded-lg border p-3 text-sm [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        info: "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200",
        success:
          "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300",
        warning:
          "border-yellow-500/30 bg-yellow-500/10 text-yellow-800 dark:text-yellow-300",
        destructive: "border-destructive/20 bg-destructive/10 text-destructive",
        muted: "border-border bg-muted/30 text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "info",
    },
  }
)

export interface AlertProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof alertVariants> {
  icon?: React.ReactNode
  title?: React.ReactNode
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant, icon, title, children, ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 space-y-1">
        {title && <div className="font-medium leading-tight">{title}</div>}
        {children && <div className="leading-snug">{children}</div>}
      </div>
    </div>
  )
)
Alert.displayName = "Alert"

export { Alert, alertVariants }
