import { EpgOutputSettings, DefaultDurations } from "@/components/EpgOutputSettings"
import { XmltvMetadataCard } from "@/components/XmltvMetadataCard"

/**
 * EPG Output — output path/window, default durations, and XMLTV generator
 * metadata. Consolidated into the EPG section in the v2.7.0 IA overhaul.
 */
export function EpgOutput() {
  return (
    <div className="space-y-2">
      <div>
        <h1 className="text-xl font-bold">EPG Output</h1>
      </div>
      <div className="space-y-4 pt-2">
        <EpgOutputSettings />
        <XmltvMetadataCard />
        <DefaultDurations />
      </div>
    </div>
  )
}
