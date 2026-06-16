import { useState } from "react"
import { toast } from "sonner"
import { Check, X, Pencil, Trash2, Loader2, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
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

/**
 * Exception Keywords management — streams matching these terms get special
 * handling during consolidation. Lifted out of Settings into the Matching home
 * (v2.7.0 IA); self-contained via its own hooks. Only relevant (and shown) when
 * global consolidation is enabled, mirroring the original Settings gate.
 */
export function ExceptionKeywordsCard() {
  const keywordsQuery = useExceptionKeywords()
  const createKeyword = useCreateExceptionKeyword()
  const deleteKeyword = useDeleteExceptionKeyword()
  const { data: channelNumbering } = useChannelNumberingSettings()

  const [newKeyword, setNewKeyword] = useState({ label: "", match_terms: "", behavior: "consolidate" })
  const [editingKeyword, setEditingKeyword] = useState<{ id: number; label: string; match_terms: string } | null>(null)

  const handleAddKeyword = async () => {
    if (!newKeyword.label.trim()) {
      toast.error("Please enter a label")
      return
    }
    if (!newKeyword.match_terms.trim()) {
      toast.error("Please enter at least one match term")
      return
    }
    try {
      await createKeyword.mutateAsync(newKeyword)
      setNewKeyword({ label: "", match_terms: "", behavior: "consolidate" })
      toast.success("Keyword added")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add keyword")
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

  const handleSaveKeywordEdit = async () => {
    if (!editingKeyword || !editingKeyword.label.trim()) {
      toast.error("Label cannot be empty")
      return
    }
    if (!editingKeyword.match_terms.trim()) {
      toast.error("Match terms cannot be empty")
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
    } catch (err) {
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
          Streams matching these terms get special handling during consolidation. The label is used for channel naming and the {"{exception_keyword}"} template variable.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="border rounded-md">
          <Table>
            <TableHeader className="bg-muted">
              <TableRow>
                <TableHead className="w-32">Label</TableHead>
                <TableHead>Match Terms (comma-separated)</TableHead>
                <TableHead className="w-40">Behavior</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keywordsQuery.data?.keywords.map((kw) => (
                <TableRow key={kw.id}>
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
                      <span className="text-muted-foreground">{kw.match_terms}</span>
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
                        } catch (err) {
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
              ))}
              {(!keywordsQuery.data?.keywords || keywordsQuery.data.keywords.length === 0) && (
                <TableRow>
                  <TableCell colSpan={4} className="py-4 text-center text-muted-foreground">
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
            placeholder="Match terms (e.g., Spanish, En Español, ESP)"
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
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
