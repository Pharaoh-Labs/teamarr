import { useEffect, useState } from "react"

/**
 * useState persisted to sessionStorage under the `teamarr.` namespace (#552).
 *
 * For list controls — filters, sort — that should survive navigating to a
 * detail page and back but need not outlive the tab: sessionStorage is
 * per-tab and cleared when it closes, so a stale filter never greets the
 * next visit. Falls back to plain in-memory state when storage is
 * unavailable (private windows, blocked site data). Values are JSON; a
 * value that fails to parse is treated as absent.
 */
export function usePersistentState<T>(key: string | null | undefined, defaultValue: T) {
  const storageKey = key ? `teamarr.${key}` : null

  const [value, setValue] = useState<T>(() => {
    if (!storageKey) return defaultValue
    try {
      const raw = sessionStorage.getItem(storageKey)
      return raw === null ? defaultValue : (JSON.parse(raw) as T)
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    if (!storageKey) return
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(value))
    } catch {
      /* ignore — non-persistent fallback */
    }
  }, [storageKey, value])

  return [value, setValue] as const
}
