import { DispatcharrOutputSettings } from "@/components/DispatcharrOutputSettings"
import { PerLeagueChannelConfig } from "@/components/PerLeagueChannelConfig"

/**
 * Channels → Dispatcharr Output. Global channel-routing defaults (profiles,
 * channel group, group mode, logo cleanup) plus the per-league overrides that
 * deviate from them. Same three knobs at two scopes — global then per-league.
 */
export function ChannelDispatcharrOutput() {
  return (
    <div className="space-y-3">
      <DispatcharrOutputSettings />
      <PerLeagueChannelConfig />
    </div>
  )
}
