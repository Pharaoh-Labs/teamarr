import { useState } from "react"
import { toast } from "sonner"
import { Loader2, TestTube, CheckCircle, XCircle, AlertTriangle } from "lucide-react"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import {
  useUpdateDispatcharrSettings,
  useTestDispatcharrConnection,
  useDispatcharrStatus,
  useDispatcharrEPGSources,
} from "@/hooks/useSettings"
import type { DispatcharrSettings } from "@/api/settings"

export function DispatcharrTab({ initial }: { initial: DispatcharrSettings }) {
  const dispatcharrStatus = useDispatcharrStatus()
  const epgSourcesQuery = useDispatcharrEPGSources(dispatcharrStatus.data?.connected ?? false)
  const updateDispatcharr = useUpdateDispatcharrSettings()
  const testConnection = useTestDispatcharrConnection()

  const [dispatcharr, setDispatcharr] = useState<Partial<DispatcharrSettings>>({
    enabled: initial.enabled,
    url: initial.url,
    username: initial.username,
    password: "", // Don't show masked password
    epg_id: initial.epg_id,
    cleanup_unused_logos: initial.cleanup_unused_logos,
  })

  const handleSaveDispatcharr = async () => {
    try {
      // Only send password if it was changed. The profile/group defaults are
      // edited on Channels → Dispatcharr Output, but the PUT treats an omitted
      // list as "set to all profiles", so echo the saved server values back.
      const data: Partial<DispatcharrSettings> = {
        enabled: dispatcharr.enabled,
        url: dispatcharr.url,
        username: dispatcharr.username,
        epg_id: dispatcharr.epg_id,
        default_channel_profile_ids: initial.default_channel_profile_ids,
        default_stream_profile_id: initial.default_stream_profile_id,
        default_channel_group_id: initial.default_channel_group_id,
        default_channel_group_mode: initial.default_channel_group_mode,
        cleanup_unused_logos: dispatcharr.cleanup_unused_logos,
      }
      if (dispatcharr.password) {
        data.password = dispatcharr.password
      }
      await updateDispatcharr.mutateAsync(data)
      toast.success("Dispatcharr settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTestConnection = async () => {
    try {
      const result = await testConnection.mutateAsync({
        url: dispatcharr.url || undefined,
        username: dispatcharr.username || undefined,
        password: dispatcharr.password || undefined,
      })
      if (result.success) {
        toast.success(`Connected! ${result.account_count} accounts, ${result.group_count} groups, ${result.channel_count} channels`)
      } else {
        toast.error(result.error || "Connection failed")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Connection test failed")
    }
  }

  return (
    <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Dispatcharr Integration</h2>
      </div>
      {/* Card 1: Connection Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Connection Settings</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={handleTestConnection} variant="outline" size="sm" disabled={testConnection.isPending}>
                {testConnection.isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {dispatcharrStatus.data?.connected ? (
                <Badge variant="success" className="gap-1">
                  <CheckCircle className="h-3 w-3" /> Connected
                </Badge>
              ) : dispatcharrStatus.data?.configured && dispatcharrStatus.data?.error ? (
                <Badge variant="destructive" className="gap-1" title={dispatcharrStatus.data.error}>
                  <AlertTriangle className="h-3 w-3" /> Error
                </Badge>
              ) : dispatcharrStatus.data?.configured ? (
                <Badge variant="warning" className="gap-1">
                  <XCircle className="h-3 w-3" /> Disconnected
                </Badge>
              ) : (
                <Badge variant="secondary">Not Configured</Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Connection error banner */}
          {dispatcharrStatus.data?.configured && dispatcharrStatus.data?.error && (
            <Alert
              variant="destructive"
              icon={<AlertTriangle className="h-4 w-4 text-destructive" />}
              title="Connection Failed"
            >
              <p className="text-muted-foreground">{dispatcharrStatus.data.error}</p>
            </Alert>
          )}

          {/* Enable */}
          <div className="flex items-center gap-2">
            <Switch
              checked={dispatcharr.enabled ?? false}
              onCheckedChange={(checked) => setDispatcharr({ ...dispatcharr, enabled: checked })}
            />
            <Label>Enable Dispatcharr Integration</Label>
          </div>

          {/* URL */}
          <div className="space-y-2">
            <Label htmlFor="dispatcharr-url">URL</Label>
            <Input
              id="dispatcharr-url"
              value={dispatcharr.url ?? ""}
              onChange={(e) => setDispatcharr({ ...dispatcharr, url: e.target.value })}
              placeholder="http://localhost:9191"
            />
          </div>

          {/* Credentials */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="dispatcharr-username">Username</Label>
              <Input
                id="dispatcharr-username"
                value={dispatcharr.username ?? ""}
                onChange={(e) => setDispatcharr({ ...dispatcharr, username: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="dispatcharr-password">Password</Label>
              <Input
                id="dispatcharr-password"
                type="password"
                value={dispatcharr.password ?? ""}
                onChange={(e) => setDispatcharr({ ...dispatcharr, password: e.target.value })}
                placeholder="Leave blank to keep current"
              />
            </div>
          </div>

          {/* Save button */}
          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
        </CardContent>
      </Card>

      {/* Card 2: EPG Source */}
      <Card>
        <CardHeader>
          <CardTitle>EPG Source</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="dispatcharr-epg">EPG Source</Label>
            <Select
              id="dispatcharr-epg"
              value={dispatcharr.epg_id?.toString() ?? ""}
              onChange={(e) =>
                setDispatcharr({
                  ...dispatcharr,
                  epg_id: e.target.value ? parseInt(e.target.value) : null,
                })
              }
              disabled={!dispatcharrStatus.data?.connected}
            >
              <option value="">Select EPG source...</option>
              {epgSourcesQuery.data?.sources?.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name} ({source.source_type})
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Associate Teamarr-managed channels with this EPG source in Dispatcharr.
            </p>
          </div>

          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
        </CardContent>
      </Card>

      {/* Card 3: Logo Cleanup — a Dispatcharr-instance housekeeping behavior, so
          it lives with the connection/EPG-source config. (Default profiles,
          channel group, and group mode moved to Channels → Dispatcharr Output in
          the v2.7.0 IA overhaul; logo cleanup is maintenance, not channel routing.) */}
      <Card>
        <CardHeader>
          <CardTitle>Logo Cleanup</CardTitle>
          <CardDescription>Remove unused logos from Dispatcharr</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Switch
                checked={dispatcharr.cleanup_unused_logos ?? false}
                onCheckedChange={(checked) =>
                  setDispatcharr({ ...dispatcharr, cleanup_unused_logos: checked })
                }
              />
              <Label>Clean up unused logos after generation</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              When enabled, removes <strong>all</strong> unused logos from Dispatcharr after EPG generation.
              This affects all unused logos, not just ones uploaded by Teamarr.
            </p>
          </div>

          <SaveButton onClick={handleSaveDispatcharr} pending={updateDispatcharr.isPending} />
        </CardContent>
      </Card>
    </>
  )
}
