import { useState, useEffect } from "react"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { RadioCards } from "@/components/ui/radio-cards"
import { ExceptionKeywordsCard } from "@/components/ExceptionKeywordsCard"
import { FeedSeparationCard } from "@/components/FeedSeparationCard"
import {
  useChannelNumberingSettings,
  useUpdateChannelNumberingSettings,
} from "@/hooks/useSettings"
import type { ChannelNumberingSettings } from "@/api/settings"

/**
 * Channels → Consolidation. How events/streams map to channels: the master
 * Consolidate/Separate default, plus the two carve-out mechanisms that split
 * channels apart — exception keywords and feed (home/away) separation.
 *
 * Stream Consolidation lives in the channel-numbering blob (full-PUT). This
 * page only edits global_consolidation_mode; numbering mode and per-league
 * starts (edited under Numbering) ride along untouched. Only one Channels view
 * mounts at a time, so the full-PUT is safe.
 */
export function ChannelConsolidation() {
  const { data: channelNumberingData } = useChannelNumberingSettings()
  const updateChannelNumbering = useUpdateChannelNumberingSettings()

  const [channelNumbering, setChannelNumbering] = useState<ChannelNumberingSettings>({
    global_channel_mode: "auto",
    league_channel_starts: {},
    global_consolidation_mode: "consolidate",
  })

  useEffect(() => {
    if (channelNumberingData) setChannelNumbering(channelNumberingData)
  }, [channelNumberingData])

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Stream Consolidation</CardTitle>
          <CardDescription>
            When an event has multiple streams, merge them into one channel or split them apart
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            <Label className="text-sm font-medium">Default Mode</Label>
            <RadioCards
              name="consolidation-mode"
              value={channelNumbering.global_consolidation_mode}
              onChange={(v) =>
                setChannelNumbering({ ...channelNumbering, global_consolidation_mode: v })
              }
              options={[
                {
                  value: "consolidate",
                  label: "Consolidate",
                  description:
                    "Merge multiple streams for the same event into one channel. Exception keywords can override per-stream.",
                },
                {
                  value: "separate",
                  label: "Separate",
                  description:
                    "Each stream gets its own channel. More channels, no merging.",
                },
              ]}
            />
          </div>

          <SaveButton
            onClick={async () => {
              try {
                await updateChannelNumbering.mutateAsync(channelNumbering)
                toast.success("Stream consolidation saved")
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Failed to save")
              }
            }}
            pending={updateChannelNumbering.isPending}
          />
        </CardContent>
      </Card>

      <ExceptionKeywordsCard />
      <FeedSeparationCard />
    </div>
  )
}
