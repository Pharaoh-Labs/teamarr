import * as React from "react"
import { Loader2, Save } from "lucide-react"
import { Button, type ButtonProps } from "@/components/ui/button"

/**
 * SaveButton — a submit/save button with a built-in pending state. Replaces the
 * `{isPending ? <Loader2 spin/> : <Save/>} Save` idiom hand-written across the
 * settings cards. When `pending`, it shows a spinner and disables itself.
 * Defaults to a Save icon + "Save" label; override via `icon` and children.
 */
export interface SaveButtonProps extends ButtonProps {
  pending?: boolean
  /** Leading icon shown when not pending. Defaults to a Save icon. */
  icon?: React.ReactNode
}

const SaveButton = React.forwardRef<HTMLButtonElement, SaveButtonProps>(
  ({ pending = false, icon, children, disabled, ...props }, ref) => (
    <Button ref={ref} disabled={disabled || pending} {...props}>
      {pending ? <Loader2 className="animate-spin" /> : (icon ?? <Save />)}
      {children ?? "Save"}
    </Button>
  )
)
SaveButton.displayName = "SaveButton"

export { SaveButton }
