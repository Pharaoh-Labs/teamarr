import { useState } from "react"
import { toast } from "sonner"
import { LoaderCircle, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { useSportLeadTimes, useSetSportLeadTime, useDeleteSportLeadTime } from "@/hooks/useSettings"
import { useSports } from "@/hooks/useSports"

/**
 * Per-sport overrides for the pre-match generation lead time. A sport with
 * no override here uses the global "Generate before each match" value set
 * above. Only relevant in pre_match scheduling mode.
 */
export function SportLeadTimeManager() {
  const overridesQuery = useSportLeadTimes()
  const sportsQuery = useSports()
  const setOverride = useSetSportLeadTime()
  const deleteOverride = useDeleteSportLeadTime()

  const overrides = overridesQuery.data ?? []
  const allSports = sportsQuery.data?.sports ?? {}
  const overriddenSports = new Set(overrides.map((o) => o.sport))
  const availableSports = Object.entries(allSports).filter(([code]) => !overriddenSports.has(code))

  const [newSport, setNewSport] = useState("")
  const [newMinutes, setNewMinutes] = useState(30)

  const handleAdd = async () => {
    if (!newSport) {
      toast.error("Please choose a sport")
      return
    }
    try {
      await setOverride.mutateAsync({ sport: newSport, minutes: newMinutes })
      setNewSport("")
      setNewMinutes(30)
      toast.success("Lead time override added")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add override")
    }
  }

  const handleUpdate = async (sport: string, minutes: number) => {
    try {
      await setOverride.mutateAsync({ sport, minutes })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update override")
    }
  }

  const handleDelete = async (sport: string) => {
    try {
      await deleteOverride.mutateAsync(sport)
      toast.success("Override removed")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove override")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Per-Sport Lead Times</CardTitle>
        <CardDescription>
          Override "Generate before each match" for specific sports — e.g. a longer lead
          for NFL pregame coverage, a shorter one for fast-moving esports. Sports without
          an override here use the global value.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {overrides.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Sport</TableHead>
                <TableHead>Lead Time (minutes)</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {overrides.map((o) => (
                <TableRow key={o.sport}>
                  <TableCell>{o.display_name ?? o.sport}</TableCell>
                  <TableCell>
                    <Input
                      type="number"
                      min={0}
                      defaultValue={o.pre_match_lead_minutes}
                      onBlur={(e) => {
                        const minutes = Number(e.target.value)
                        if (minutes !== o.pre_match_lead_minutes) {
                          handleUpdate(o.sport, minutes)
                        }
                      }}
                      className="max-w-[8rem]"
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDelete(o.sport)}
                      disabled={deleteOverride.isPending}
                      title="Remove override"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Sport</label>
            <Select
              value={newSport}
              onChange={(e) => setNewSport(e.target.value)}
              className="min-w-[12rem]"
            >
              <option value="">Choose a sport...</option>
              {availableSports.map(([code, displayName]) => (
                <option key={code} value={code}>
                  {displayName}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Minutes</label>
            <Input
              type="number"
              min={0}
              value={newMinutes}
              onChange={(e) => setNewMinutes(Number(e.target.value))}
              className="max-w-[8rem]"
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={handleAdd}
            disabled={setOverride.isPending || !newSport}
          >
            {setOverride.isPending ? (
              <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Plus className="h-4 w-4 mr-1" />
            )}
            Add Override
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
