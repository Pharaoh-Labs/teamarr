import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Tag, Trash2, LoaderCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { LeaguePicker } from "@/components/LeaguePicker"
import {
  listGracenoteOverrides,
  getGracenoteCategory,
  putGracenoteCategory,
} from "@/api/leagueOverrides"

/**
 * Gracenote category overrides (#371) — per-league customization of the
 * {gracenote_category} template variable. Overrides survive startup re-seeds
 * (they live outside the leagues table) and apply immediately.
 */
export function GracenoteOverridesCard() {
  const queryClient = useQueryClient()
  const [selectedLeagues, setSelectedLeagues] = useState<string[]>([])
  const [value, setValue] = useState("")
  const league = selectedLeagues[0] ?? null

  const overridesQuery = useQuery({
    queryKey: ["gracenote-overrides"],
    queryFn: listGracenoteOverrides,
  })
  const stateQuery = useQuery({
    queryKey: ["gracenote-category", league],
    queryFn: () => getGracenoteCategory(league!),
    enabled: league !== null,
  })

  const saveMutation = useMutation({
    mutationFn: ({ code, val }: { code: string; val: string | null }) =>
      putGracenoteCategory(code, val),
    onSuccess: (state) => {
      queryClient.invalidateQueries({ queryKey: ["gracenote-overrides"] })
      queryClient.invalidateQueries({ queryKey: ["gracenote-category", state.league_code] })
      toast.success(
        state.override
          ? `{gracenote_category} for ${state.league_code} is now "${state.effective}"`
          : `${state.league_code} restored to default "${state.default}"`,
      )
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Failed to save override"),
  })

  const handleSave = () => {
    if (!league) return
    saveMutation.mutate({ code: league, val: value.trim() || null })
    setValue("")
  }

  const overrides = overridesQuery.data?.overrides ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Tag className="h-5 w-5" />
          Gracenote Category Overrides
        </CardTitle>
        <CardDescription>
          Customize what <code>{"{gracenote_category}"}</code> renders for a league
          (e.g. program titles like &ldquo;NFL Football&rdquo;). Overrides survive
          updates and apply immediately; clear one to restore the built-in value.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <LeaguePicker
            selectedLeagues={selectedLeagues}
            onSelectionChange={setSelectedLeagues}
            singleSelect
            maxHeight="max-h-48"
          />
          <div className="flex flex-col gap-2">
            {league && stateQuery.data && (
              <p className="text-sm text-muted-foreground">
                Current: <span className="font-medium">{stateQuery.data.effective}</span>
                {stateQuery.data.override && (
                  <> (default: {stateQuery.data.default})</>
                )}
              </p>
            )}
            <div className="flex gap-2">
              <Input
                placeholder={
                  league
                    ? (stateQuery.data?.default ?? "Category text")
                    : "Select a league first"
                }
                value={value}
                onChange={(e) => setValue(e.target.value)}
                disabled={!league}
              />
              <Button onClick={handleSave} disabled={!league || !value.trim() || saveMutation.isPending}>
                {saveMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : "Save"}
              </Button>
            </div>
          </div>
        </div>

        {overrides.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>League</TableHead>
                <TableHead>Override</TableHead>
                <TableHead>Default</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {overrides.map((o) => (
                <TableRow key={o.league_code}>
                  <TableCell className="font-mono text-sm">{o.league_code}</TableCell>
                  <TableCell>{o.gracenote_category}</TableCell>
                  <TableCell className="text-muted-foreground">{o.default}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      title="Clear override (restore default)"
                      onClick={() => saveMutation.mutate({ code: o.league_code, val: null })}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
