import { StreamOrderingManager } from "@/components/StreamOrderingManager"

/**
 * Channels → Stream Priority. Rules that decide which stream wins inside a
 * single channel (by M3U account, event group, or custom pattern). Distinct
 * from channel ordering (lineup position), which lives under Numbering.
 */
export function ChannelStreamPriority() {
  return <StreamOrderingManager />
}
