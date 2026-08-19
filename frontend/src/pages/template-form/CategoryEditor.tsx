import { useState } from "react"
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
  const [focused, setFocused] = useState(false)

  // Sync from outside when the category list changes externally (form reset
  // or initial load) — but NEVER while the input is focused (#423): the
  // derived list legitimately shifts as a consequence of the user's own
  // keystrokes (e.g. typed text temporarily equals a checkbox-owned name and
  // dedupes to nothing), and any re-seed mid-typing swallows their text.
  // Blur canonicalizes the input from the parsed state instead.
  const joinedCustom = customCategories.join(",")
  const [syncedJoined, setSyncedJoined] = useState(joinedCustom)
  if (!focused && joinedCustom !== syncedJoined) {
    setSyncedJoined(joinedCustom)
    const currentParsed = customInput
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
    if (joinedCustom !== currentParsed.join(",")) {
      setCustomInput(customCategories.join(", "))
    }
  }

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
      // Checkbox-owned names must not enter the custom list (#423): a typed
      // "Sports" with the Sports checkbox on would duplicate in `value`, the
      // derived custom list would filter BOTH copies out, and the sync branch
      // above would clobber the input mid-typing — swallowing "Sports event"
      // at the final "s" of "Sports".
      .filter((s) => s && s !== "Sports" && s !== "{sport}")
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
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false)
            // Canonicalize from parsed state: drops checkbox-owned names the
            // user typed (they live in the checkboxes, not the custom list).
            setCustomInput(customCategories.join(", "))
            setSyncedJoined(joinedCustom)
          }}
          placeholder={customPlaceholder}
        />
        <p className="text-xs text-muted-foreground">{helperText}</p>
      </div>
    </div>
  )
}
