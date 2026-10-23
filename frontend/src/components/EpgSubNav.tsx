import { SubNav } from "@/components/ui/sub-nav"

/**
 * Shared secondary navigation for the EPG section (v2.7.0 IA).
 * Three views: Templates (table + assignments), Team EPG, EPG Output.
 */
export function EpgSubNav() {
  return (
    <SubNav
      items={[
        { key: "/epg/templates", label: "Templates", to: "/epg/templates" },
        { key: "/epg/teams", label: "Team EPG", to: "/epg/teams" },
        { key: "/epg/output", label: "EPG Output", to: "/epg/output" },
      ]}
    />
  )
}
