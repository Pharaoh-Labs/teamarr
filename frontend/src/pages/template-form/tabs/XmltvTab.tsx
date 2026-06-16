import { FolderOpen, Clapperboard, Tag, Tv } from "lucide-react"
import { Alert } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import type { XmltvFlags } from "@/api/templates"
import { CategoryEditor } from "../CategoryEditor"
import type { TabProps } from "../types"

export function XmltvTab({ formData, setFormData }: TabProps) {
  const flags = formData.xmltv_flags || { new: true, live: false, date: false }
  const eventCategories = formData.xmltv_categories || ["Sports"]
  const fillerCategories = formData.xmltv_filler_categories || []

  const updateFlags = (field: keyof XmltvFlags, value: boolean) => {
    setFormData((prev) => {
      const current = prev.xmltv_flags || { new: true, live: false, date: false }
      return { ...prev, xmltv_flags: { ...current, [field]: value } }
    })
  }

  const setEventCategories = (next: string[]) =>
    setFormData((prev) => ({ ...prev, xmltv_categories: next }))
  const setFillerCategories = (next: string[]) =>
    setFormData((prev) => ({ ...prev, xmltv_filler_categories: next }))

  return (
    <div className="space-y-6">
      {/* Categories — split between event programmes and filler programmes (#199) */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2"><FolderOpen className="h-4 w-4" /> Event Categories</CardTitle>
            <p className="text-xs text-muted-foreground">
              Applied to live game programmes (events).
            </p>
          </CardHeader>
          <CardContent>
            <CategoryEditor
              value={eventCategories}
              onChange={setEventCategories}
              showSportVarOption={true}
              customPlaceholder="e.g., Entertainment, Live Events"
              helperText="Categories shown on event programmes in the EPG guide."
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2"><Clapperboard className="h-4 w-4" /> Filler Categories</CardTitle>
            <p className="text-xs text-muted-foreground">
              Applied to filler programmes (pregame / postgame / idle). Independent from event
              categories — leave empty to omit <code>&lt;category&gt;</code> tags on filler.
            </p>
          </CardHeader>
          <CardContent>
            <CategoryEditor
              value={fillerCategories}
              onChange={setFillerCategories}
              showSportVarOption={true}
              customPlaceholder="e.g., Series (Emby guide-view compat)"
              helperText="Common need: add 'Series' so Emby displays the sub-title in guide view."
            />
          </CardContent>
        </Card>
      </div>

      {/* Tags */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2"><Tag className="h-4 w-4" /> Tags</CardTitle>
          <p className="text-xs text-muted-foreground">
            Tags only apply to events, not to filler (pregame/postgame/idle).
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={flags.new} onCheckedChange={() => updateFlags("new", !flags.new)} />
            <div>
              <span>Include New Tag</span>
              <p className="text-xs text-muted-foreground">Adds &lt;new/&gt; tag to events</p>
            </div>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={flags.live} onCheckedChange={() => updateFlags("live", !flags.live)} />
            <div>
              <span>Include Live Tag</span>
              <p className="text-xs text-muted-foreground">Adds &lt;live/&gt; tag to events</p>
            </div>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={flags.date} onCheckedChange={() => updateFlags("date", !flags.date)} />
            <div>
              <span>Include Date Tag</span>
              <p className="text-xs text-muted-foreground">Adds &lt;date&gt; tag with air date (YYYYMMDD) to events</p>
            </div>
          </label>
        </CardContent>
      </Card>

      {/* Video Quality */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2"><Tv className="h-4 w-4" /> Video Quality</CardTitle>
          <p className="text-xs text-muted-foreground">
            XMLTV video element for EPG clients that support quality metadata.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <Alert variant="warning" className="text-xs">
            <strong>Note:</strong> Teamarr does not detect actual stream resolution. This setting will apply to <strong>all</strong> channels using this template, regardless of their actual quality.
          </Alert>
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={formData.xmltv_video?.enabled || false}
              onCheckedChange={() => setFormData(prev => ({
                ...prev,
                xmltv_video: { ...prev.xmltv_video, enabled: !prev.xmltv_video?.enabled }
              }))}
            />
            <div>
              <span>Include Video Element</span>
              <p className="text-xs text-muted-foreground">Adds &lt;video&gt;&lt;quality&gt; element</p>
            </div>
          </label>
          {formData.xmltv_video?.enabled && (
            <div className="pt-2">
              <label className="text-xs font-medium">Quality</label>
              <Select
                className="mt-1"
                value={formData.xmltv_video?.quality || "HDTV"}
                onChange={(e) => setFormData(prev => ({
                  ...prev,
                  xmltv_video: { ...prev.xmltv_video, quality: e.target.value }
                }))}
              >
                <option value="SDTV">SDTV</option>
                <option value="HDTV">HDTV</option>
                <option value="UHD">UHD (4K)</option>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
