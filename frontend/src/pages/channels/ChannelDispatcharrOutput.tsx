import { DispatcharrOutputSettings } from "@/components/DispatcharrOutputSettings"
import { PerLeagueChannelConfig } from "@/components/PerLeagueChannelConfig"

/**
 * Channels → Dispatcharr Output. Global channel-routing defaults (profiles,
 * channel group, group mode) plus the per-league overrides that deviate from
 * them. Same three knobs at two scopes — global then per-league.
 *
 * Logo cleanup is NOT here — it's Settings → Dispatcharr (maintenance, not
 * channel routing, per the v2.7.0 IA split). This page's payload still
 * round-trips cleanup_unused_logos without editing it.
 */
export function ChannelDispatcharrOutput() {
  return (
    <div className="space-y-3">
      <DispatcharrOutputSettings />
      <PerLeagueChannelConfig />
    </div>
  )
}
