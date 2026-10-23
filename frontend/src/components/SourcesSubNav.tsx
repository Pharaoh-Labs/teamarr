import { SubNav } from "@/components/ui/sub-nav"

/**
 * Shared secondary navigation for the Sources section (#1131).
 * Schedule inputs live here: M3U/stream sources today, manual events now,
 * ICS calendars as a further tab later.
 */
export function SourcesSubNav() {
  return (
    <SubNav
      items={[
        { key: "/sources", label: "Stream Sources", to: "/sources" },
        { key: "/sources/manual-events", label: "Manual Events", to: "/sources/manual-events" },
      ]}
    />
  )
}
