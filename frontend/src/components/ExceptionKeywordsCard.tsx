import { Fragment, useState } from "react"
import { toast } from "sonner"
import { Check, X, Pencil, Trash2, LoaderCircle, Plus, SlidersHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import {
  useExceptionKeywords,
  useCreateExceptionKeyword,
  useDeleteExceptionKeyword,
  useChannelNumberingSettings,
} from "@/hooks/useSettings"
import { updateExceptionKeyword, type KeywordMatchSources } from "@/api/settings"
import { KeywordSourcesEditor } from "@/components/KeywordSourcesEditor"
import { EMPTY_SOURCES, countSources } from "@/lib/keyword-sources"

/**
 * Exception Keywords management — streams matching these terms get special
 * handling during consolidation. Lifted out of Settings into the Matching home
 * (v2.7.0 IA); self-contained via its own hooks. Only relevant (and shown) when
 * global consolidation is enabled, mirroring the original Settings gate.
 */
export function ExceptionKeywordsCard() {
  // include_disabled=true (#522): a keyword disabled via the API used to
  // vanish from this card entirely, leaving no way to re-enable it from the UI.
  const keywordsQuery = useExceptionKeywords(true)
  const createKeyword = useCreateExceptionKeyword()
  const deleteKeyword = useDeleteExceptionKeyword()
  const { data: channelNumbering } = useChannelNumberingSettings()

  const [newKeyword, setNewKeyword] = useState({ label: "", match_terms: "", behavior: "consolidate" })
  const [editingKeyword, setEditingKeyword] = useState<{ id: number; label: string; match_terms: string } | null>(null)
  // Which keyword's match-sources editor is open; "new" = the add row (#893)
  const [sourcesFor, setSourcesFor] = useState<number | "new" | null>(null)
  const [savingSources, setSavingSources] = useState(false)

  const createNewKeyword = async (sources?: KeywordMatchSources) => {
    try {
      await createKeyword.mutateAsync({ ...newKeyword, ...sources })
      setNewKeyword({ label: "", match_terms: "", behavior: "consolidate" })
      setSourcesFor(null)
      toast.success("Keyword added")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add keyword")
    }
  }

  const handleAddKeyword = async () => {
    if (!newKeyword.label.trim()) {
      toast.error("Please enter a label")
      return
    }
    if (!newKeyword.match_terms.trim()) {
      // No terms: the keyword needs another match source before it can exist.
      setSourcesFor("new")
      return
    }
    await createNewKeyword()
  }

  const handleSaveSources = async (sources: KeywordMatchSources) => {
    setSavingSources(true)
    try {
      if (sourcesFor === "new") {
        await createNewKeyword(sources)
      } else if (sourcesFor !== null) {
        await updateExceptionKeyword(sourcesFor, sources)
        await keywordsQuery.refetch()
        setSourcesFor(null)
        toast.success("Match sources saved")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save match sources")
    } finally {
      setSavingSources(false)
    }
  }

  const handleDeleteKeyword = async (id: number) => {
    try {
      await deleteKeyword.mutateAsync(id)
      toast.success("Keyword deleted")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete keyword")
    }
  }

  const handleToggleEnabled = async (id: number, enabled: boolean) => {
    try {
      await updateExceptionKeyword(id, { enabled })
      keywordsQuery.refetch()
      toast.success(enabled ? "Keyword enabled" : "Keyword disabled")
    } catch {
      toast.error("Failed to update keyword")
    }
  }

  const handleSaveKeywordEdit = async () => {
    if (!editingKeyword || !editingKeyword.label.trim()) {
      toast.error("Label cannot be empty")
      return
    }
    const current = keywordsQuery.data?.keywords.find((k) => k.id === editingKeyword.id)
    if (!editingKeyword.match_terms.trim() && !(current && countSources(current) > 0)) {
      toast.error("Match terms cannot be empty unless the keyword has other match sources")
      return
    }
    try {
      await fetch(`/api/v1/keywords/${editingKeyword.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: editingKeyword.label, match_terms: editingKeyword.match_terms }),
      })
      keywordsQuery.refetch()
      setEditingKeyword(null)
      toast.success("Keyword updated")
    } catch {
      toast.error("Failed to update keyword")
    }
  }

  // Only relevant when global consolidation is on (mirrors the original gate).
  if (channelNumbering?.global_consolidation_mode !== "consolidate") return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Exception Keywords</CardTitle>
        <CardDescription>
          Streams matching these terms, or coming from the M3U groups, event groups or pinned streams set under
          {" "}<SlidersHorizontal className="inline h-3 w-3" /> Match sources, get special handling during consolidation.
          The label is used for channel naming, the {"{exception_keyword}"} template variable and group patterns.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="border rounded-md">
          <Table>
            <TableHeader className="bg-muted">
              <TableRow>
                <TableHead className="w-12">On</TableHead>
                <TableHead className="w-32">Label</TableHead>
                <TableHead>Match Terms (comma-separated)</TableHead>
                <TableHead className="w-40">Behavior</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keywordsQuery.data?.keywords.map((kw) => (
                <Fragment key={kw.id}>
                <TableRow className={kw.enabled === false ? "opacity-50" : undefined}>
                  <TableCell>
                    <Checkbox
                      checked={kw.enabled !== false}
                      onCheckedChange={(checked) => handleToggleEnabled(kw.id, !!checked)}
                      aria-label={kw.enabled === false ? "Enable keyword" : "Disable keyword"}
                    />
                  </TableCell>
                  <TableCell>
                    {editingKeyword?.id === kw.id ? (
                      <Input
                        value={editingKeyword.label}
                        onChange={(e) => setEditingKeyword({ ...editingKeyword, label: e.target.value })}
                        className="h-8"
                        autoFocus
                        placeholder="Label"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleSaveKeywordEdit()
                          if (e.key === "Escape") setEditingKeyword(null)
                        }}
                      />
                    ) : (
                      <span className="font-medium">{kw.label}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {editingKeyword?.id === kw.id ? (
                      <Input
                        value={editingKeyword.match_terms}
                        onChange={(e) => setEditingKeyword({ ...editingKeyword, match_terms: e.target.value })}
                        className="h-8"
                        placeholder="Terms to match"
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleSaveKeywordEdit()
                          if (e.key === "Escape") setEditingKeyword(null)
                        }}
                      />
                    ) : (
                      <span className="text-muted-foreground">{kw.match_terms || "—"}</span>
                    )}
                    {countSources(kw) > 0 && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        + {countSources(kw)} source{countSources(kw) === 1 ? "" : "s"}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={kw.behavior}
                      onChange={async (e) => {
                        const newBehavior = e.target.value
                        try {
                          await fetch(`/api/v1/keywords/${kw.id}`, {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ behavior: newBehavior }),
                          })
                          keywordsQuery.refetch()
                          toast.success(`Updated behavior to "${newBehavior}"`)
                        } catch {
                          toast.error("Failed to update keyword behavior")
                        }
                      }}
                      className="w-40 h-8"
                      disabled={editingKeyword?.id === kw.id}
                    >
                      <option value="consolidate">Sub-Consolidate</option>
                      <option value="separate">Separate</option>
                      <option value="ignore">Ignore</option>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {editingKeyword?.id === kw.id ? (
                        <>
                          <Button variant="ghost" size="sm" onClick={handleSaveKeywordEdit} title="Save">
                            <Check className="h-4 w-4 text-green-600" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setEditingKeyword(null)} title="Cancel">
                            <X className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditingKeyword({ id: kw.id, label: kw.label, match_terms: kw.match_terms })}
                            title="Edit"
                          >
                            <Pencil className="h-4 w-4 text-muted-foreground" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSourcesFor(sourcesFor === kw.id ? null : kw.id)}
                            title="Match sources"
                          >
                            <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteKeyword(kw.id)}
                            disabled={deleteKeyword.isPending}
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
                {sourcesFor === kw.id && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <KeywordSourcesEditor
                        initial={{
                          m3u_group_pattern: kw.m3u_group_pattern,
                          m3u_groups: kw.m3u_groups,
                          stream_pattern: kw.stream_pattern,
                          streams: kw.streams,
                          event_group_ids: kw.event_group_ids,
                        }}
                        saving={savingSources}
                        onSave={handleSaveSources}
                        onCancel={() => setSourcesFor(null)}
                      />
                    </TableCell>
                  </TableRow>
                )}
                </Fragment>
              ))}
              {(!keywordsQuery.data?.keywords || keywordsQuery.data.keywords.length === 0) && (
                <TableRow>
                  <TableCell colSpan={5} className="py-4 text-center text-muted-foreground">
                    No exception keywords defined
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        <div className="flex flex-col sm:flex-row gap-2">
          <Input
            placeholder="Label (e.g., Spanish)"
            value={newKeyword.label}
            onChange={(e) => setNewKeyword({ ...newKeyword, label: e.target.value })}
            className="w-full sm:w-32"
          />
          <Input
            placeholder="Match terms (e.g., Spanish, En Español, ESP), or leave empty to match by source"
            value={newKeyword.match_terms}
            onChange={(e) => setNewKeyword({ ...newKeyword, match_terms: e.target.value })}
            className="w-full sm:flex-1"
          />
          <Select
            value={newKeyword.behavior}
            onChange={(e) => setNewKeyword({ ...newKeyword, behavior: e.target.value })}
            className="w-full sm:w-40"
          >
            <option value="consolidate">Sub-Consolidate</option>
            <option value="separate">Separate</option>
            <option value="ignore">Ignore</option>
          </Select>
          <Button onClick={handleAddKeyword} disabled={createKeyword.isPending} className="w-full sm:w-auto">
            {createKeyword.isPending ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
          </Button>
        </div>
        {sourcesFor === "new" && (
          <KeywordSourcesEditor
            initial={EMPTY_SOURCES}
            saving={savingSources || createKeyword.isPending}
            onSave={handleSaveSources}
            onCancel={() => setSourcesFor(null)}
          />
        )}
      </CardContent>
    </Card>
  )
}
