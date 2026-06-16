import { SubNav } from "@/components/ui/sub-nav"

/**
 * Secondary navigation for the Channels section (v2.7.0 IA). Five views split
 * out of the old single-scroll Channels page:
 *  - Lifecycle: create/delete timing + buffers
 *  - Consolidation: stream consolidation + exception keywords + feed separation
 *  - Numbering: numbering mode/ranges/per-league starts + channel ordering
 *  - Stream Priority: within-channel stream priority rules
 *  - Dispatcharr Output: global routing defaults + per-league overrides
 */
export function ChannelsSubNav() {
  return (
    <SubNav
      items={[
        { key: "/channels/lifecycle", label: "Lifecycle", to: "/channels/lifecycle" },
        { key: "/channels/consolidation", label: "Consolidation", to: "/channels/consolidation" },
        { key: "/channels/numbering", label: "Numbering", to: "/channels/numbering" },
        { key: "/channels/stream-priority", label: "Stream Priority", to: "/channels/stream-priority" },
        { key: "/channels/output", label: "Dispatcharr Output", to: "/channels/output" },
      ]}
    />
  )
}
