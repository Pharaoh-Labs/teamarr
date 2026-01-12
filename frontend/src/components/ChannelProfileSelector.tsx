import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Plus, X, Loader2, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"

interface ChannelProfile {
  id: number
  name: string
}

async function fetchChannelProfiles(): Promise<ChannelProfile[]> {
  const response = await fetch("/api/v1/dispatcharr/channel-profiles")
  if (!response.ok) {
    if (response.status === 503) return [] // Dispatcharr not connected
    throw new Error("Failed to fetch channel profiles")
  }
  return response.json()
}

async function createChannelProfile(name: string): Promise<ChannelProfile | null> {
  const response = await fetch(
    `/api/v1/dispatcharr/channel-profiles?name=${encodeURIComponent(name)}`,
    { method: "POST" }
  )
  if (!response.ok) return null
  return response.json()
}

interface ChannelProfileSelectorProps {
  /** Currently selected profile IDs */
  selectedIds: number[]
  /** Callback when selection changes */
  onChange: (ids: number[]) => void
  /** Whether Dispatcharr is connected */
  disabled?: boolean
  /** Optional class name */
  className?: string
}

/**
 * Channel profile multi-select with inline creation.
 *
 * Behavior:
 * - All profiles checked = all profiles
 * - No profiles checked = no profiles
 * - Some profiles checked = those specific profiles
 */
export function ChannelProfileSelector({
  selectedIds,
  onChange,
  disabled = false,
  className,
}: ChannelProfileSelectorProps) {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState("")
  const [creating, setCreating] = useState(false)

  const { data: profiles = [], isLoading } = useQuery({
    queryKey: ["dispatcharr-channel-profiles"],
    queryFn: fetchChannelProfiles,
    retry: false,
  })

  const selectedSet = new Set(selectedIds)
  const allSelected = profiles.length > 0 && profiles.every(p => selectedSet.has(p.id))
  const noneSelected = selectedIds.length === 0

  const toggleProfile = (id: number) => {
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter(x => x !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const selectAll = () => {
    onChange(profiles.map(p => p.id))
  }

  const clearAll = () => {
    onChange([])
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const created = await createChannelProfile(newName.trim())
      if (created) {
        toast.success(`Created profile "${created.name}"`)
        // Add to selection
        onChange([...selectedIds, created.id])
        setNewName("")
        setShowCreate(false)
        queryClient.invalidateQueries({ queryKey: ["dispatcharr-channel-profiles"] })
      } else {
        toast.error("Failed to create profile")
      }
    } catch {
      toast.error("Failed to create profile")
    }
    setCreating(false)
  }

  if (isLoading) {
    return (
      <div className={cn("flex items-center justify-center py-4", className)}>
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className={cn("space-y-2", className)}>
      {/* Header with actions */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {noneSelected
            ? "No profiles selected"
            : allSelected
              ? `All ${profiles.length} profiles`
              : `${selectedIds.length} of ${profiles.length} profiles`}
        </span>
        <div className="flex items-center gap-1">
          {!allSelected && profiles.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={selectAll}
              disabled={disabled}
            >
              Select All
            </Button>
          )}
          {!noneSelected && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={clearAll}
              disabled={disabled}
            >
              Clear
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            onClick={() => setShowCreate(!showCreate)}
            disabled={disabled}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Create new profile */}
      {showCreate && (
        <div className="flex gap-2 p-2 bg-muted/50 rounded-md">
          <Input
            placeholder="New profile name..."
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="flex-1 h-8"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                handleCreate()
              }
            }}
          />
          <Button
            type="button"
            size="sm"
            className="h-8"
            disabled={creating || !newName.trim()}
            onClick={handleCreate}
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2"
            onClick={() => {
              setShowCreate(false)
              setNewName("")
            }}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Profile list */}
      <div className="border rounded-md divide-y max-h-48 overflow-y-auto">
        {profiles.length === 0 ? (
          <div className="p-3 text-sm text-muted-foreground text-center">
            {disabled ? "Dispatcharr not connected" : "No profiles found"}
          </div>
        ) : (
          profiles.map((profile) => {
            const isSelected = selectedSet.has(profile.id)
            return (
              <label
                key={profile.id}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent",
                  isSelected && "bg-primary/5",
                  disabled && "opacity-50 cursor-not-allowed"
                )}
              >
                <Checkbox
                  checked={isSelected}
                  onCheckedChange={() => !disabled && toggleProfile(profile.id)}
                  disabled={disabled}
                />
                <span className="text-sm flex-1">{profile.name}</span>
                {isSelected && <Check className="h-4 w-4 text-primary" />}
              </label>
            )
          })
        )}
      </div>
    </div>
  )
}

/**
 * Convert selected IDs to API format.
 * - All profiles selected → [0] (sentinel for "all", auto-includes new profiles)
 * - No profiles selected → [] (no profiles)
 * - Some profiles selected → those IDs
 */
export function profileIdsToApi(
  selectedIds: number[],
  allProfileIds: number[]
): number[] | null {
  if (selectedIds.length === 0) {
    return [] // No profiles
  }
  // Check if all profiles are selected
  const selectedSet = new Set(selectedIds)
  const allSelected = allProfileIds.length > 0 &&
    allProfileIds.every(id => selectedSet.has(id))

  if (allSelected) {
    return null // null = all profiles (backend sends [0] to Dispatcharr)
  }
  return selectedIds
}

/**
 * Convert API format to selected IDs for display.
 * - null or [0] → select all profiles
 * - [] → select none
 * - [1,2,...] → select those
 */
export function apiToProfileIds(
  apiValue: number[] | null | undefined,
  allProfileIds: number[]
): number[] {
  if (apiValue === null || apiValue === undefined) {
    // null = all profiles
    return [...allProfileIds]
  }
  if (apiValue.length === 1 && apiValue[0] === 0) {
    // [0] sentinel = all profiles
    return [...allProfileIds]
  }
  return apiValue
}
