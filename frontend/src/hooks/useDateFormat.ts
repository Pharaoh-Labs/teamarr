import { useCallback, useMemo } from "react"
import { useDisplaySettings, useSettings } from "./useSettings"

/**
 * Hook for formatting dates according to user preferences.
 * Uses UI timezone for display and display settings (time_format, show_timezone).
 *
 * UI timezone is either:
 * - From TZ environment variable (immutable)
 * - Falls back to EPG timezone setting (user-configurable)
 */
export function useDateFormat() {
  const { data: displaySettings } = useDisplaySettings()
  const { data: settings } = useSettings()

  // Use UI timezone for display (falls back to EPG timezone if not set via env var)
  const timezone = settings?.ui_timezone || "UTC"
  const timezoneSource = settings?.ui_timezone_source || "epg"
  const timeFormat = displaySettings?.time_format || "12h"
  const showTimezone = displaySettings?.show_timezone ?? true

  // Build Intl.DateTimeFormat options
  const formatOptions = useMemo((): Intl.DateTimeFormatOptions => {
    const options: Intl.DateTimeFormatOptions = {
      timeZone: timezone,
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: timeFormat === "12h",
    }

    if (showTimezone) {
      options.timeZoneName = "short"
    }

    return options
  }, [timezone, timeFormat, showTimezone])

  // Create formatter
  const formatter = useMemo(
    () => new Intl.DateTimeFormat("en-US", formatOptions),
    [formatOptions]
  )

  // Format a date string or Date object
  const formatDateTime = useCallback(
    (dateStr: string | Date | null): string => {
      if (!dateStr) return "-"
      try {
        const date = typeof dateStr === "string" ? new Date(dateStr) : dateStr
        if (isNaN(date.getTime())) return "-"
        return formatter.format(date)
      } catch {
        return "-"
      }
    },
    [formatter]
  )

  // Format relative time (e.g., "5m ago")
  const formatRelativeTime = useCallback(
    (dateStr: string | null): string => {
      if (!dateStr) return "Never"
      const date = new Date(dateStr)
      if (isNaN(date.getTime())) return "Never"

      const now = new Date()
      const diffMs = now.getTime() - date.getTime()
      const diffMins = Math.floor(diffMs / 60000)
      const diffHours = Math.floor(diffMins / 60)
      const diffDays = Math.floor(diffHours / 24)

      if (diffMins < 1) return "Just now"
      if (diffMins < 60) return `${diffMins}m ago`
      if (diffHours < 24) return `${diffHours}h ago`
      return `${diffDays}d ago`
    },
    []
  )

  // Format with both absolute and relative (e.g., "Dec 24, 3:45 PM EST (5m ago)")
  const formatDateTimeWithRelative = useCallback(
    (dateStr: string | null): string => {
      if (!dateStr) return "-"
      const absolute = formatDateTime(dateStr)
      const relative = formatRelativeTime(dateStr)
      if (absolute === "-" || relative === "Never") return absolute
      return `${absolute} (${relative})`
    },
    [formatDateTime, formatRelativeTime]
  )

  return {
    formatDateTime,
    formatRelativeTime,
    formatDateTimeWithRelative,
    timezone,
    timezoneSource,
    timeFormat,
    showTimezone,
  }
}
