import { useState } from "react"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { useSettings, useUpdateLifecycleSettings } from "@/hooks/useSettings"
import type { LifecycleSettings } from "@/api/settings"

/**
 * Channels → Lifecycle. When event channels are created and deleted, plus the
 * pre/post-event buffers. The lifecycle blob also carries channel range (edited
 * under Numbering) — this page loads the full object and full-PUTs it, so the
 * range fields ride along untouched. Only one Channels view mounts at a time,
 * so the full-PUT is safe (same pattern as the EPG settings pages).
 */
export function ChannelLifecycle() {
  const { data: settings } = useSettings()
  const updateLifecycle = useUpdateLifecycleSettings()

  const [lifecycle, setLifecycle] = useState<LifecycleSettings | null>(null)

  // Seed local state from the server blob during render (React's "adjusting
  // state when a prop changes" pattern). The previous effect seeded ONCE
  // (initRef guard) — `lifecycle === null` preserves that: it is only null
  // before the first seed, and every later setLifecycle spreads a non-null
  // object, so refetches never re-seed.
  if (settings && lifecycle === null) {
    setLifecycle(settings.lifecycle)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Channel Lifecycle</CardTitle>
        <CardDescription>
          Configure when channels are created and deleted for event groups
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="ch-create-timing">Channel Create Timing</Label>
            <Select
              id="ch-create-timing"
              value={lifecycle?.channel_create_timing ?? "same_day"}
              onChange={(e) =>
                lifecycle && setLifecycle({ ...lifecycle, channel_create_timing: e.target.value })
              }
            >
              <option value="same_day">Same day</option>
              <option value="before_event">Before event + buffer</option>
            </Select>
            <Label htmlFor="ch-pre-buffer" className={lifecycle?.channel_create_timing !== "before_event" ? "text-muted-foreground" : ""}>
              Pre-Event Buffer (hours)
            </Label>
            <Input
              id="ch-pre-buffer"
              type="number"
              min={0}
              max={336}
              disabled={lifecycle?.channel_create_timing !== "before_event"}
              value={Math.round((lifecycle?.channel_pre_buffer_minutes ?? 60) / 60)}
              onChange={(e) => {
                const val = parseInt(e.target.value)
                if (!isNaN(val) && lifecycle) {
                  setLifecycle({ ...lifecycle, channel_pre_buffer_minutes: Math.max(0, Math.min(336, val)) * 60 })
                }
              }}
            />
            <p className="text-xs text-muted-foreground">
              {lifecycle?.channel_create_timing === "before_event"
                ? "Hours before event start to create channel"
                : " "}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="ch-delete-timing">Channel Delete Timing</Label>
            <Select
              id="ch-delete-timing"
              value={lifecycle?.channel_delete_timing ?? "same_day"}
              onChange={(e) =>
                lifecycle && setLifecycle({ ...lifecycle, channel_delete_timing: e.target.value })
              }
            >
              <option value="same_day">Same day</option>
              <option value="after_event">After event + buffer</option>
            </Select>
            <Label htmlFor="ch-post-buffer">Post-Event Buffer (hours)</Label>
            <Input
              id="ch-post-buffer"
              type="number"
              min={0}
              max={336}
              value={Math.round((lifecycle?.channel_post_buffer_minutes ?? 60) / 60)}
              onChange={(e) => {
                const val = parseInt(e.target.value)
                if (!isNaN(val) && lifecycle) {
                  setLifecycle({ ...lifecycle, channel_post_buffer_minutes: Math.max(0, Math.min(336, val)) * 60 })
                }
              }}
            />
            <p className="text-xs text-muted-foreground">
              {lifecycle?.channel_delete_timing === "after_event"
                ? "Hours after event ends to delete channel"
                : "Midnight cross-over events will always use post-event buffer"}
            </p>
          </div>
        </div>

        <SaveButton
          onClick={async () => {
            if (!lifecycle) return
            try {
              await updateLifecycle.mutateAsync(lifecycle)
              toast.success("Channel lifecycle settings saved")
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Failed to save")
            }
          }}
          pending={updateLifecycle.isPending}
        />
      </CardContent>
    </Card>
  )
}
