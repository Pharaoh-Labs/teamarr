import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { TabProps } from "../types"

// fieldRefs aliased to a *Ref name so the React Compiler recognizes it as a
// ref and allows the ref-callback mutation (its ref detection is name-based).
export function BasicTab({ formData, setFormData, fieldRefs: fieldRefsRef, setLastFocusedField }: TabProps) {
  return (
    <div className="space-y-6">
      {/* Template Name */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Template Name</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <Label htmlFor="name">Name *</Label>
            <Input
              id="name"
              ref={(el) => {
                if (fieldRefsRef) fieldRefsRef.current["name"] = el
              }}
              value={formData.name}
              onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
              onFocus={() => setLastFocusedField?.("name")}
              placeholder="e.g., NFL Default, NBA Premium"
            />
          </div>
        </CardContent>
      </Card>

      {/* Event Duration */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Event Duration</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-3">
            Global and Per-Sport Defaults can be changed in Settings
          </p>
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="duration_mode"
                checked={formData.game_duration_mode === "sport"}
                onChange={() => setFormData((prev) => ({ ...prev, game_duration_mode: "sport", game_duration_override: null }))}
                className="accent-primary"
              />
              <span>Use Per-Sport Default</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="duration_mode"
                checked={formData.game_duration_mode === "default"}
                onChange={() => setFormData((prev) => ({ ...prev, game_duration_mode: "default", game_duration_override: null }))}
                className="accent-primary"
              />
              <span>Use Global Default</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="duration_mode"
                checked={formData.game_duration_mode === "custom"}
                onChange={() => setFormData((prev) => ({ ...prev, game_duration_mode: "custom" }))}
                className="accent-primary"
              />
              <span>Custom:</span>
              <Input
                type="number"
                step="0.25"
                min="1"
                max="8"
                value={formData.game_duration_override ?? ""}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    game_duration_mode: "custom",
                    game_duration_override: e.target.value ? parseFloat(e.target.value) : null,
                  }))
                }
                disabled={formData.game_duration_mode !== "custom"}
                className="w-20 h-8"
                placeholder="3.5"
              />
              <span>hours</span>
            </label>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
