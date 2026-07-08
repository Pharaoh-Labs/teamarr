import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

const SIZES = {
  sm: "h-4 w-4",
  md: "h-6 w-6",
  lg: "h-8 w-8",
} as const

/** Centered loading spinner block for tables, sections, and pages. */
export function Spinner({
  size = "md",
  className,
}: {
  size?: keyof typeof SIZES
  className?: string
}) {
  return (
    <div className={cn("flex items-center justify-center py-8", className)}>
      <Loader2 className={cn(SIZES[size], "animate-spin text-muted-foreground")} />
    </div>
  )
}
