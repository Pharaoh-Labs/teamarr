import { useState, useEffect, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { Plus, Trash2, Download, Upload, Search, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import {
  useAliases,
  useCreateAlias,
  useDeleteAlias,
  exportAliases,
  useImportAliases,
} from "@/api/aliases"
import { getLeagues } from "@/api/teams"
import type { TeamAliasCreate, TeamFilterEntry } from "@/api/types"
import { TeamPicker } from "@/components/TeamPicker"

export function TeamAliases() {
  const [leagueFilter, setLeagueFilter] = useState<string>("")
  const [searchQuery, setSearchQuery] = useState("")
  const [isCreateOpen, setIsCreateOpen] = useState(false)

  // Form state for create dialog
  const [aliasText, setAliasText] = useState("")
  const [selectedSport, setSelectedSport] = useState("")
  const [selectedLeague, setSelectedLeague] = useState("")
  const [selectedTeams, setSelectedTeams] = useState<TeamFilterEntry[]>([])

  const { data, isLoading } = useAliases(leagueFilter || undefined)
  const createMutation = useCreateAlias()
  const deleteMutation = useDeleteAlias()
  const importMutation = useImportAliases()

  // Fetch all leagues for dropdown
  const { data: leaguesData, isLoading: leaguesLoading } = useQuery({
    queryKey: ["cache", "leagues"],
    queryFn: () => getLeagues(false),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Sort leagues by sport then name
  const sortedLeagues = useMemo(() => {
    if (!leaguesData?.leagues) return []
    return [...leaguesData.leagues].sort((a, b) => {
      const sportCompare = a.sport.localeCompare(b.sport)
      if (sportCompare !== 0) return sportCompare
      return a.name.localeCompare(b.name)
    })
  }, [leaguesData?.leagues])

  // Get unique sports sorted alphabetically
  const sports = useMemo(() => {
    const sportSet = new Set(sortedLeagues.map((l) => l.sport))
    return [...sportSet].sort()
  }, [sortedLeagues])

  // Filter leagues by selected sport
  const filteredLeagues = useMemo(() => {
    if (!selectedSport) return []
    return sortedLeagues.filter((l) => l.sport === selectedSport)
  }, [sortedLeagues, selectedSport])

  // Get selected team from TeamPicker selection
  const selectedTeam = selectedTeams[0] || null

  // Get unique leagues for filter dropdown (from existing aliases)
  const existingLeagues = [...new Set(data?.aliases.map((a) => a.league) || [])]

  // Filter aliases by search query
  const filteredAliases = (data?.aliases || []).filter((alias) => {
    const query = searchQuery.toLowerCase()
    return (
      alias.alias.toLowerCase().includes(query) ||
      alias.team_name.toLowerCase().includes(query) ||
      alias.league.toLowerCase().includes(query)
    )
  })

  // Reset form when dialog closes
  useEffect(() => {
    if (!isCreateOpen) {
      setAliasText("")
      setSelectedSport("")
      setSelectedLeague("")
      setSelectedTeams([])
    }
  }, [isCreateOpen])

  // Clear league and team when sport changes
  useEffect(() => {
    setSelectedLeague("")
    setSelectedTeams([])
  }, [selectedSport])

  // Clear team selection when league changes
  useEffect(() => {
    setSelectedTeams([])
  }, [selectedLeague])

  const handleCreate = async () => {
    if (!selectedTeam || !selectedLeague || !aliasText) return

    const newAlias: TeamAliasCreate = {
      alias: aliasText.toLowerCase().trim(),
      league: selectedLeague,
      team_id: selectedTeam.team_id,
      team_name: selectedTeam.name || "",
      provider: selectedTeam.provider,
    }

    try {
      await createMutation.mutateAsync(newAlias)
      setIsCreateOpen(false)
    } catch {
      // Error shown by mutation
    }
  }

  const handleExport = async () => {
    try {
      const aliases = await exportAliases()
      const blob = new Blob([JSON.stringify(aliases, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "team_aliases.json"
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error("Export failed:", e)
    }
  }

  const handleImport = () => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".json"
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      try {
        const text = await file.text()
        const aliases = JSON.parse(text)
        await importMutation.mutateAsync(aliases)
      } catch (e) {
        console.error("Import failed:", e)
      }
    }
    input.click()
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Team Aliases</h1>
          <p className="text-sm text-muted-foreground">
            Define custom name mappings for stream matching
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4 mr-1" />
            Export
          </Button>
          <Button variant="outline" size="sm" onClick={handleImport}>
            <Upload className="h-4 w-4 mr-1" />
            Import
          </Button>
          <Button size="sm" onClick={() => setIsCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            Add Alias
          </Button>
        </div>
      </div>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent onClose={() => setIsCreateOpen(false)} className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Create Team Alias</DialogTitle>
            <DialogDescription>
              Map a stream name to a team for better matching
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {/* Alias Text */}
            <div className="space-y-2">
              <Label htmlFor="alias">Alias Text *</Label>
              <Input
                id="alias"
                value={aliasText}
                onChange={(e) => setAliasText(e.target.value)}
                placeholder="e.g., Spurs, Man U, NYG"
              />
              <p className="text-xs text-muted-foreground">
                The text that appears in stream names (case-insensitive)
              </p>
            </div>

            {/* Sport Dropdown */}
            <div className="space-y-2">
              <Label htmlFor="sport">Sport *</Label>
              {leaguesLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading...
                </div>
              ) : (
                <Select
                  id="sport"
                  value={selectedSport}
                  onChange={(e) => setSelectedSport(e.target.value)}
                >
                  <option value="">Select a sport...</option>
                  {sports.map((sport) => (
                    <option key={sport} value={sport}>
                      {sport}
                    </option>
                  ))}
                </Select>
              )}
            </div>

            {/* League Dropdown */}
            <div className="space-y-2">
              <Label htmlFor="league">League *</Label>
              {!selectedSport ? (
                <p className="text-sm text-muted-foreground py-2">
                  Select a sport first
                </p>
              ) : (
                <Select
                  id="league"
                  value={selectedLeague}
                  onChange={(e) => setSelectedLeague(e.target.value)}
                >
                  <option value="">Select a league...</option>
                  {filteredLeagues.map((league) => (
                    <option key={league.slug} value={league.slug}>
                      {league.name} ({league.team_count} teams)
                    </option>
                  ))}
                </Select>
              )}
            </div>

            {/* Team Selection */}
            <div className="space-y-2">
              <Label>Team *</Label>
              {!selectedLeague ? (
                <p className="text-sm text-muted-foreground py-2">
                  Select a league first
                </p>
              ) : (
                <TeamPicker
                  leagues={[selectedLeague]}
                  selectedTeams={selectedTeams}
                  onSelectionChange={setSelectedTeams}
                  placeholder="Search teams..."
                  singleSelect
                />
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                !aliasText.trim() ||
                !selectedLeague ||
                !selectedTeam ||
                createMutation.isPending
              }
            >
              {createMutation.isPending ? "Creating..." : "Create Alias"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Filter Bar */}
      <div className="flex gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search aliases..."
            className="pl-10"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <Select
          className="w-48"
          value={leagueFilter}
          onChange={(e) => setLeagueFilter(e.target.value)}
        >
          <option value="">All Leagues</option>
          {existingLeagues.map((league) => (
            <option key={league} value={league}>
              {league}
            </option>
          ))}
        </Select>
      </div>

      {/* Aliases Table */}
      <div className="border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filteredAliases.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            {searchQuery || leagueFilter ? "No aliases match your filters" : "No aliases defined yet"}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Alias</TableHead>
                <TableHead>League</TableHead>
                <TableHead>Team Name</TableHead>
                <TableHead>Team ID</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead className="w-16"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredAliases.map((alias) => (
                <TableRow key={alias.id}>
                  <TableCell className="font-medium">{alias.alias}</TableCell>
                  <TableCell>
                    <code className="bg-muted px-1 py-0.5 rounded text-sm">{alias.league}</code>
                  </TableCell>
                  <TableCell>{alias.team_name}</TableCell>
                  <TableCell className="font-mono text-sm">{alias.team_id}</TableCell>
                  <TableCell className="capitalize">{alias.provider}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteMutation.mutate(alias.id)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* How It Works */}
      <div className="border border-border rounded-lg p-4">
        <h3 className="font-medium mb-2">How It Works</h3>
        <div className="text-sm text-muted-foreground space-y-2">
          <p>
            Team aliases help with stream matching when automatic fuzzy matching fails.
            Common use cases:
          </p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li><strong>Nicknames:</strong> "Spurs" → "Tottenham Hotspur" (EPL) or "San Antonio Spurs" (NBA)</li>
            <li><strong>Abbreviations:</strong> "Man U" → "Manchester United"</li>
            <li><strong>Local Names:</strong> "NYG" → "New York Giants"</li>
          </ul>
          <p>
            Aliases are league-specific so "Spurs" can map to different teams in different leagues.
          </p>
        </div>
      </div>
    </div>
  )
}
