import { useState, useEffect } from "react"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

// Reusable category editor — renders the Sports / {sport} checkboxes plus a
// comma-separated custom-category input. Used twice in XmltvTab: once for
// event categories, once for filler categories. The two instances are
// independent (#199).
export function CategoryEditor({
  value,
  onChange,
  showSportVarOption,
  customPlaceholder,
  helperText,
}: {
  value: string[]
  onChange: (next: string[]) => void
  showSportVarOption: boolean
  customPlaceholder: string
  helperText: string
}) {
  const hasSports = value.includes("Sports")
  const hasSportVar = value.includes("{sport}")
  const customCategories = value.filter((c) => c !== "Sports" && c !== "{sport}")

  const [customInput, setCustomInput] = useState(customCategories.join(", "))

  // Sync from outside when the category list changes externally (form reset
  // or initial load), but not while user is mid-typing.
  useEffect(() => {
    const currentParsed = customInput
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
    if (customCategories.join(",") !== currentParsed.join(",")) {
      setCustomInput(customCategories.join(", "))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customCategories.join(",")])

  const toggle = (cat: string, checked: boolean) => {
    if (checked) {
      onChange([...value, cat])
    } else {
      onChange(value.filter((c) => c !== cat))
    }
  }

  const updateCustom = (text: string) => {
    setCustomInput(text)
    const custom = text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
    const base = [hasSports && "Sports", showSportVarOption && hasSportVar && "{sport}"].filter(
      Boolean,
    ) as string[]
    onChange([...base, ...custom])
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Common Categories</Label>
        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox checked={hasSports} onCheckedChange={() => toggle("Sports", !hasSports)} />
            <span>Sports</span>
          </label>
          {showSportVarOption && (
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={hasSportVar}
                onCheckedChange={() => toggle("{sport}", !hasSportVar)}
              />
              <span>
                <code>{"{sport}"}</code> - Auto-populates with team's sport (Basketball,
                Football, etc.)
              </span>
            </label>
          )}
        </div>
      </div>

      <div className="space-y-1">
        <Label>Custom Categories (comma-separated)</Label>
        <Input
          value={customInput}
          onChange={(e) => updateCustom(e.target.value)}
          placeholder={customPlaceholder}
        />
        <p className="text-xs text-muted-foreground">{helperText}</p>
      </div>
    </div>
  )
}
