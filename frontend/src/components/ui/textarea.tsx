import * as React from "react"
import { cn } from "@/lib/utils"

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          // V1-matching: solid background, visible border, proper text color
          "flex min-h-[60px] w-full rounded-md border border-input px-3 py-2 text-sm shadow-sm transition-colors",
          "bg-secondary text-foreground",
          "placeholder:text-muted-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:border-primary",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Textarea.displayName = "Textarea"

/**
 * Textarea that starts at one line and grows with its content — an Input-feel
 * field for template strings that outgrow a single line (no inner scrollbar,
 * no manual resize handle).
 */
const AutoGrowTextarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    const innerRef = React.useRef<HTMLTextAreaElement | null>(null)

    // Re-fit after every render: value changes arrive via props (controlled),
    // not just user input, so onChange alone would miss programmatic updates.
    React.useLayoutEffect(() => {
      const el = innerRef.current
      if (!el) return
      el.style.height = "auto"
      el.style.height = `${el.scrollHeight}px`
    })

    return (
      <Textarea
        ref={(el) => {
          innerRef.current = el
          if (typeof ref === "function") ref(el)
          else if (ref) ref.current = el
        }}
        rows={1}
        className={cn("min-h-9 resize-none overflow-hidden", className)}
        {...props}
      />
    )
  }
)
AutoGrowTextarea.displayName = "AutoGrowTextarea"

export { Textarea, AutoGrowTextarea }
