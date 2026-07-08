import { useState } from "react"
import { EpgMatchingSettings, EventLookaheadSetting } from "@/components/EventMatchingSettings"
import { SubNav } from "@/components/ui/sub-nav"
import { AliasesSection } from "./detection-library/AliasesSection"
import { KeywordSections } from "./detection-library/KeywordSections"

/**
 * Matching page — EPG matching settings, event lookahead, and the custom-rules
 * detection library (team aliases + keyword categories, each self-contained in
 * pages/detection-library/).
 */
export function DetectionLibrary() {
  const [activeView, setActiveView] = useState<
    "custom_rules" | "epg_matching" | "event_lookahead"
  >("epg_matching")

  return (
    <div className="space-y-2">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-xl font-bold shrink-0">Matching</h1>
        {/* Custom Regex signpost — compact one-liner beside the heading */}
        <div className="rounded-md border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950 px-3 py-1.5 text-xs text-blue-800 dark:text-blue-200 sm:whitespace-nowrap">
          <span className="font-semibold text-blue-900 dark:text-blue-100">Tip:</span>{" "}
          per-source <strong>Custom Regex</strong> is your strongest matching lever — set it in Sources.
        </div>
      </div>

      {/* Page-level view nav */}
      <SubNav
        items={[
          { key: "epg_matching", label: "EPG Matching" },
          { key: "event_lookahead", label: "Event Lookahead" },
          { key: "custom_rules", label: "Custom Rules" },
        ]}
        value={activeView}
        onChange={(k) =>
          setActiveView(k as "custom_rules" | "epg_matching" | "event_lookahead")
        }
      />

      {activeView === "epg_matching" && <EpgMatchingSettings />}

      {activeView === "event_lookahead" && <EventLookaheadSetting />}

      {activeView === "custom_rules" && (
        <div className="space-y-4">
          <AliasesSection />
          <KeywordSections />
        </div>
      )}
    </div>
  )
}
