import { useMemo } from "react"
import cronstrue from "cronstrue"

/**
 * Render a human-readable description of a cron expression, or an error line
 * if it can't be parsed. Shared by the scheduled-generation, channel-reset, and
 * backup cards.
 */
export function CronPreview({ expression }: { expression: string }) {
  const humanReadable = useMemo(() => {
    try {
      return cronstrue.toString(expression, {
        throwExceptionOnParseError: false,
        verbose: true,
      })
    } catch {
      return null
    }
  }, [expression])

  if (!humanReadable) {
    return <p className="text-xs text-destructive">Invalid cron expression</p>
  }

  return <p className="text-xs text-muted-foreground">{humanReadable}</p>
}
