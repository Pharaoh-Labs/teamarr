import { useState, useEffect } from "react"
import { toast } from "sonner"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { useDisplaySettings, useUpdateDisplaySettings } from "@/hooks/useSettings"
import type { DisplaySettings } from "@/api/settings"

/**
 * XMLTV Generator Metadata — edits the generator name/url written into the
 * XMLTV output header. Lifted out of Settings into EPG → EPG Output (v2.7.0 IA).
 * Self-contained: loads the COMPLETE display settings blob and saves it whole so
 * the other display fields aren't clobbered.
 */
export function XmltvMetadataCard() {
  const { data: displayData } = useDisplaySettings()
  const updateDisplay = useUpdateDisplaySettings()

  const [display, setDisplay] = useState<DisplaySettings | null>(null)

  useEffect(() => {
    if (displayData) setDisplay(displayData)
  }, [displayData])

  const handleSave = async () => {
    if (!display) return
    try {
      await updateDisplay.mutateAsync(display)
      toast.success("XMLTV metadata saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>XMLTV Generator Metadata</CardTitle>
        <CardDescription>Generator name and URL written into the XMLTV output header</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="xmltv-name">XMLTV Generator Name</Label>
            <Input
              id="xmltv-name"
              value={display?.xmltv_generator_name ?? "Teamarr"}
              onChange={(e) => display && setDisplay({ ...display, xmltv_generator_name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="xmltv-url">XMLTV Generator URL</Label>
            <Input
              id="xmltv-url"
              value={display?.xmltv_generator_url ?? "https://github.com/Pharaoh-Labs/teamarr"}
              onChange={(e) => display && setDisplay({ ...display, xmltv_generator_url: e.target.value })}
              placeholder="https://github.com/Pharaoh-Labs/teamarr"
            />
          </div>
        </div>

        <SaveButton onClick={handleSave} pending={updateDisplay.isPending} />
      </CardContent>
    </Card>
  )
}
