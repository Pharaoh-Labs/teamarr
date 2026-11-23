/**
 * Dispatcharr's `audio_channels` stat as a speaker layout ("2.0", "5.1").
 *
 * The value arrives three ways (#1150): a channel count from Dispatcharr's own
 * probe ("2", 6), an ffprobe layout word from tools that push stats ("stereo",
 * "5.1", "5.1(side)", "mono"), or "0" when the probe could not tell. Returns
 * null for anything that is not a known layout, so the caller shows nothing.
 *
 * Mirrors `_audio_channel_count` in `teamarr/services/stream_ordering.py`.
 */

const LAYOUT_BY_COUNT: Record<number, string> = {
  1: "1.0",
  2: "2.0",
  3: "2.1",
  4: "4.0",
  5: "5.0",
  6: "5.1",
  7: "6.1",
  8: "7.1",
}

const LAYOUT_BY_WORD: Record<string, string> = {
  mono: "1.0",
  stereo: "2.0",
  quad: "4.0",
}

const LAYOUT_SHAPE = /^[1-9]\.[01]$/

export function audioChannelLayout(raw: unknown): string | null {
  if (raw == null) return null
  if (typeof raw === "number") return LAYOUT_BY_COUNT[raw] ?? null
  // "5.1(side)" and "7.1(wide)" are the same layout for this purpose.
  const text = String(raw).trim().toLowerCase().split("(", 1)[0].trim()
  if (!text) return null
  if (text in LAYOUT_BY_WORD) return LAYOUT_BY_WORD[text]
  // A layout written as a number ("5.1", "2.0") is a layout, not a count.
  if (LAYOUT_SHAPE.test(text)) return text
  return /^\d+$/.test(text) ? (LAYOUT_BY_COUNT[Number(text)] ?? null) : null
}
