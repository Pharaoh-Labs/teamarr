import { useState, useMemo } from "react"
import { toast } from "sonner"
import {
  Plus,
  Trash2,
  RefreshCw,
  Loader2,
  Link2,
  Unlink,
  Satellite,
  ChevronDown,
  ChevronRight,
  Check,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  listSources,
  createSource,
  deleteSource,
  refreshSource,
  updateSource,
  listAllChannels,
  listMappings,
  createMapping,
  deleteMapping,
  toggleMapping,
  getDispatcharrStreams,
  listProgrammes,
  type EPGChannel,
  type DispatcharrStream,
} from "@/api/epgSources"

type TabId = "sources" | "mapping" | "active"

export function EPGSources() {
  const [activeTab, setActiveTab] = useState<TabId>("sources")

  const tabs: { id: TabId; label: string }[] = [
    { id: "sources", label: "Sources" },
    { id: "mapping", label: "Channel Mapping" },
    { id: "active", label: "Active Mappings" },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">EPG Sources</h1>
          <p className="text-sm text-muted-foreground">
            External XMLTV feeds for sports event discovery
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "sources" && <SourcesTab />}
      {activeTab === "mapping" && <MappingTab />}
      {activeTab === "active" && <ActiveMappingsTab />}
    </div>
  )
}

// =============================================================================
// SOURCES TAB
// =============================================================================

function SourcesTab() {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState("")
  const [newUrl, setNewUrl] = useState("")
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [refreshingId, setRefreshingId] = useState<number | null>(null)

  const sourcesQuery = useQuery({
    queryKey: ["epg-sources"],
    queryFn: () => listSources(true),
  })

  const addMutation = useMutation({
    mutationFn: () => createSource({ name: newName, url: newUrl }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-sources"] })
      setShowAdd(false)
      setNewName("")
      setNewUrl("")
      toast.success("EPG source added")
    },
    onError: (e: Error) => toast.error(`Failed to add source: ${e.message}`),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSource(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-sources"] })
      setDeleteId(null)
      toast.success("Source deleted")
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      updateSource(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-sources"] })
    },
  })

  async function handleRefresh(id: number) {
    setRefreshingId(id)
    try {
      const result = await refreshSource(id)
      toast.success(
        `Refreshed: ${result.channels} channels, ${result.programmes} programmes`
      )
      queryClient.invalidateQueries({ queryKey: ["epg-sources"] })
      queryClient.invalidateQueries({ queryKey: ["epg-channels"] })
    } catch (e: any) {
      toast.error(`Refresh failed: ${e.message}`)
    } finally {
      setRefreshingId(null)
    }
  }

  const sources = sourcesQuery.data?.sources ?? []

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus className="h-4 w-4 mr-1" /> Add Source
        </Button>
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>URL</TableHead>
              <TableHead className="text-center">Channels</TableHead>
              <TableHead className="text-center">Programmes</TableHead>
              <TableHead className="text-center">Status</TableHead>
              <TableHead className="text-center">Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sources.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  <Satellite className="h-8 w-8 mx-auto mb-2 opacity-40" />
                  No EPG sources configured. Add one to get started.
                </TableCell>
              </TableRow>
            ) : (
              sources.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="max-w-[300px] truncate text-xs text-muted-foreground">
                    {s.url}
                  </TableCell>
                  <TableCell className="text-center">{s.channel_count}</TableCell>
                  <TableCell className="text-center">{s.programme_count}</TableCell>
                  <TableCell className="text-center">
                    {s.last_fetch_status === "success" ? (
                      <Badge variant="default" className="bg-green-600">OK</Badge>
                    ) : s.last_fetch_status === "error" ? (
                      <Badge variant="destructive" title={s.last_fetch_error || ""}>
                        Error
                      </Badge>
                    ) : (
                      <Badge variant="secondary">Never fetched</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={!!s.enabled}
                      onCheckedChange={(v) =>
                        toggleMutation.mutate({ id: s.id, enabled: v })
                      }
                    />
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleRefresh(s.id)}
                      disabled={refreshingId === s.id}
                    >
                      {refreshingId === s.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() => setDeleteId(s.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      {/* Add Source Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add EPG Source</DialogTitle>
            <DialogDescription>
              Add an external XMLTV EPG feed URL. Supports plain XML and gzip
              compressed files.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>Name</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g., My EPG Provider"
              />
            </div>
            <div>
              <Label>URL</Label>
              <Input
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                placeholder="https://example.com/epg.xml.gz"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowAdd(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => addMutation.mutate()}
              disabled={!newName.trim() || !newUrl.trim() || addMutation.isPending}
            >
              {addMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              ) : null}
              Add Source
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <Dialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Source</DialogTitle>
            <DialogDescription>
              This will delete the source and all its channels, mappings, and
              cached programmes. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteId && deleteMutation.mutate(deleteId)}
              disabled={deleteMutation.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// =============================================================================
// MAPPING TAB
// =============================================================================

function MappingTab() {
  const queryClient = useQueryClient()
  const [selectedChannel, setSelectedChannel] = useState<EPGChannel | null>(null)
  const [selectedStream, setSelectedStream] = useState<DispatcharrStream | null>(null)
  const [channelSearch, setChannelSearch] = useState("")
  const [streamSearch, setStreamSearch] = useState("")
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set())

  const channelsQuery = useQuery({
    queryKey: ["epg-channels"],
    queryFn: listAllChannels,
  })

  const streamsQuery = useQuery({
    queryKey: ["dispatcharr-streams"],
    queryFn: getDispatcharrStreams,
  })

  const mappingsQuery = useQuery({
    queryKey: ["epg-mappings"],
    queryFn: () => listMappings(false),
  })

  const mapMutation = useMutation({
    mutationFn: () => {
      if (!selectedChannel || !selectedStream) throw new Error("Select both sides")
      return createMapping({
        epg_channel_id: selectedChannel.id,
        dispatcharr_stream_id: selectedStream.id,
        dispatcharr_stream_name: selectedStream.name,
        m3u_account_id: selectedStream.m3u_account_id ?? undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-mappings"] })
      setSelectedChannel(null)
      setSelectedStream(null)
      toast.success("Mapping created")
    },
    onError: (e: Error) => toast.error(`Failed: ${e.message}`),
  })

  const channels = channelsQuery.data?.channels ?? []
  const streams = streamsQuery.data?.streams ?? []
  const mappings = mappingsQuery.data?.mappings ?? []

  // Already-mapped IDs
  const mappedStreamIds = useMemo(
    () => new Set(mappings.map((m) => m.dispatcharr_stream_id)),
    [mappings]
  )
  const mappedChannelIds = useMemo(
    () => new Set(mappings.map((m) => m.epg_channel_id)),
    [mappings]
  )

  // Group channels by source
  const channelsBySource = useMemo(() => {
    const map: Record<string, { sourceName: string; sourceId: number; channels: EPGChannel[] }> = {}
    for (const ch of channels) {
      const key = String(ch.source_id)
      if (!map[key]) {
        map[key] = { sourceName: ch.source_name, sourceId: ch.source_id, channels: [] }
      }
      map[key].channels.push(ch)
    }
    return Object.values(map)
  }, [channels])

  // Filter
  const filteredStreams = useMemo(() => {
    const q = streamSearch.toLowerCase()
    return streams
      .filter((s) => !mappedStreamIds.has(s.id))
      .filter((s) => !q || s.name.toLowerCase().includes(q))
  }, [streams, streamSearch, mappedStreamIds])

  const toggleSource = (id: number) => {
    setExpandedSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-4">
      {/* Assignment bar */}
      <Card className="p-4">
        <div className="flex items-center gap-4">
          <div className="flex-1 text-sm">
            <span className="text-muted-foreground">EPG Channel: </span>
            {selectedChannel ? (
              <Badge variant="secondary">{selectedChannel.display_name}</Badge>
            ) : (
              <span className="italic text-muted-foreground">Select from left</span>
            )}
          </div>
          <Link2 className="h-4 w-4 text-muted-foreground" />
          <div className="flex-1 text-sm">
            <span className="text-muted-foreground">Stream: </span>
            {selectedStream ? (
              <Badge variant="secondary">{selectedStream.name}</Badge>
            ) : (
              <span className="italic text-muted-foreground">Select from right</span>
            )}
          </div>
          <Button
            size="sm"
            disabled={!selectedChannel || !selectedStream || mapMutation.isPending}
            onClick={() => mapMutation.mutate()}
          >
            {mapMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Check className="h-4 w-4 mr-1" />
            )}
            Assign
          </Button>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        {/* Left: EPG Channels */}
        <Card className="overflow-hidden">
          <div className="p-3 border-b border-border">
            <Input
              placeholder="Search EPG channels..."
              value={channelSearch}
              onChange={(e) => setChannelSearch(e.target.value)}
              className="h-8"
            />
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {channelsBySource.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground text-sm">
                No EPG channels. Add and refresh a source first.
              </div>
            ) : (
              channelsBySource.map((group) => {
                const expanded = expandedSources.has(group.sourceId)
                const filtered = group.channels.filter(
                  (ch) =>
                    !channelSearch ||
                    ch.display_name
                      .toLowerCase()
                      .includes(channelSearch.toLowerCase())
                )
                if (channelSearch && filtered.length === 0) return null

                return (
                  <div key={group.sourceId}>
                    <button
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium bg-secondary/30 hover:bg-secondary/50 border-b border-border"
                      onClick={() => toggleSource(group.sourceId)}
                    >
                      {expanded ? (
                        <ChevronDown className="h-3 w-3" />
                      ) : (
                        <ChevronRight className="h-3 w-3" />
                      )}
                      {group.sourceName}
                      <Badge variant="secondary" className="ml-auto text-xs">
                        {filtered.length}
                      </Badge>
                    </button>
                    {expanded &&
                      filtered.map((ch) => {
                        const isMapped = mappedChannelIds.has(ch.id)
                        const isSelected = selectedChannel?.id === ch.id
                        return (
                          <button
                            key={ch.id}
                            onClick={() => !isMapped && setSelectedChannel(ch)}
                            disabled={isMapped}
                            className={`w-full text-left px-4 py-1.5 text-sm border-b border-border/50 transition-colors ${
                              isSelected
                                ? "bg-primary/10 text-primary"
                                : isMapped
                                  ? "opacity-40 cursor-not-allowed"
                                  : "hover:bg-secondary/30"
                            }`}
                          >
                            <span className="truncate block">
                              {ch.display_name}
                            </span>
                            {isMapped && (
                              <span className="text-xs text-muted-foreground">
                                (already mapped)
                              </span>
                            )}
                          </button>
                        )
                      })}
                  </div>
                )
              })
            )}
          </div>
        </Card>

        {/* Right: Dispatcharr Streams */}
        <Card className="overflow-hidden">
          <div className="p-3 border-b border-border">
            <Input
              placeholder="Search streams..."
              value={streamSearch}
              onChange={(e) => setStreamSearch(e.target.value)}
              className="h-8"
            />
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {streamsQuery.isLoading ? (
              <div className="p-8 text-center">
                <Loader2 className="h-6 w-6 animate-spin mx-auto" />
              </div>
            ) : filteredStreams.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground text-sm">
                {streamSearch
                  ? "No matching streams"
                  : "No unmapped streams available"}
              </div>
            ) : (
              filteredStreams.map((s) => {
                const isSelected = selectedStream?.id === s.id
                return (
                  <button
                    key={s.id}
                    onClick={() => setSelectedStream(s)}
                    className={`w-full text-left px-4 py-1.5 text-sm border-b border-border/50 transition-colors ${
                      isSelected
                        ? "bg-primary/10 text-primary"
                        : "hover:bg-secondary/30"
                    }`}
                  >
                    <span className="truncate block">{s.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {s.group_name}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

// =============================================================================
// ACTIVE MAPPINGS TAB
// =============================================================================

function ActiveMappingsTab() {
  const queryClient = useQueryClient()
  const [previewChannelId, setPreviewChannelId] = useState<number | null>(null)

  const mappingsQuery = useQuery({
    queryKey: ["epg-mappings"],
    queryFn: () => listMappings(false),
  })

  const programmesQuery = useQuery({
    queryKey: ["epg-programmes", previewChannelId],
    queryFn: () =>
      previewChannelId ? listProgrammes(previewChannelId) : Promise.resolve({ programmes: [] }),
    enabled: previewChannelId !== null,
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteMapping(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-mappings"] })
      toast.success("Mapping removed")
    },
  })

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      toggleMapping(id, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["epg-mappings"] })
    },
  })

  const mappings = mappingsQuery.data?.mappings ?? []
  const programmes = programmesQuery.data?.programmes ?? []

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>EPG Channel</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Stream</TableHead>
              <TableHead className="text-center">Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {mappings.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  No mappings yet. Go to the Channel Mapping tab to create one.
                </TableCell>
              </TableRow>
            ) : (
              mappings.map((m) => (
                <TableRow key={m.id}>
                  <TableCell>
                    <button
                      className="text-left hover:text-primary transition-colors"
                      onClick={() =>
                        setPreviewChannelId(
                          previewChannelId === m.epg_channel_id
                            ? null
                            : m.epg_channel_id
                        )
                      }
                    >
                      <span className="font-medium">{m.epg_channel_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {m.channel_xmltv_id}
                      </span>
                    </button>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {m.source_name}
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">
                      {m.dispatcharr_stream_name || `Stream #${m.dispatcharr_stream_id}`}
                    </span>
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={!!m.enabled}
                      onCheckedChange={(v) =>
                        toggleMut.mutate({ id: m.id, enabled: v })
                      }
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() => deleteMut.mutate(m.id)}
                    >
                      <Unlink className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      {/* Programme Preview */}
      {previewChannelId !== null && (
        <Card className="p-4">
          <h3 className="text-sm font-medium mb-3">
            Programme Preview
            {programmesQuery.isLoading && (
              <Loader2 className="h-3 w-3 animate-spin inline ml-2" />
            )}
          </h3>
          {programmes.length === 0 && !programmesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">
              No programmes found for this channel.
            </p>
          ) : (
            <div className="max-h-[300px] overflow-y-auto space-y-1">
              {programmes.slice(0, 50).map((p) => (
                <div
                  key={p.id}
                  className="flex items-center gap-3 text-sm py-1 border-b border-border/30"
                >
                  <span className="text-xs text-muted-foreground w-[140px] shrink-0">
                    {formatTime(p.start_time)} - {formatTime(p.stop_time)}
                  </span>
                  <span className="truncate">{p.title}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}
