import { useState } from "react"
import { toast } from "sonner"
import { LoaderCircle, TestTube, CircleCheckBig, CircleX, TriangleAlert, KeyRound } from "lucide-react"
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
  useAdoptDispatcharrApiKey,
  useTestDispatcharrConnection,
  useDispatcharrStatus,
  useDispatcharrEPGSources,
} from "@/hooks/useSettings"
import type { DispatcharrSettings } from "@/api/settings"

export function DispatcharrTab({ initial }: { initial: DispatcharrSettings }) {
  const dispatcharrStatus = useDispatcharrStatus()
  const epgSourcesQuery = useDispatcharrEPGSources(dispatcharrStatus.data?.connected ?? false)
  const updateDispatcharr = useUpdateDispatcharrSettings()
  const adoptApiKey = useAdoptDispatcharrApiKey()
  const testConnection = useTestDispatcharrConnection()

  const [dispatcharr, setDispatcharr] = useState<Partial<DispatcharrSettings>>({
    enabled: initial.enabled,
    url: initial.url,
    username: initial.username,
    password: "", // Don't show masked password
    api_key: "", // Don't show masked key either
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
        untagged_keyword_label: initial.untagged_keyword_label,
        managed_team_channel_profile_ids: initial.managed_team_channel_profile_ids,
        managed_team_channel_group_id: initial.managed_team_channel_group_id,
        cleanup_unused_logos: dispatcharr.cleanup_unused_logos,
      }
      if (dispatcharr.password) {
        data.password = dispatcharr.password
      }
      if (dispatcharr.api_key) {
        data.api_key = dispatcharr.api_key
      }
      await updateDispatcharr.mutateAsync(data)
      toast.success("Dispatcharr settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  // One click from saved username/password to a key: the backend adopts the
  // key already on the Dispatcharr account, or mints one only when there is
  // none — Dispatcharr keeps one key per user and generating replaces it (#817).
  const handleAdoptApiKey = async () => {
    try {
      const result = await adoptApiKey.mutateAsync()
      if (result.success) {
        toast.success(
          result.created
            ? "Generated an API key on your Dispatcharr account and saved it"
            : "Adopted your Dispatcharr account's API key",
        )
      } else {
        toast.error(result.error || "Could not switch to an API key")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not switch to an API key")
    }
  }

  // An empty string tells the backend to drop the stored key, so the
  // connection goes back to the username and password (#817).
  const handleRemoveApiKey = async () => {
    try {
      await updateDispatcharr.mutateAsync({ api_key: "" })
      setDispatcharr({ ...dispatcharr, api_key: "" })
      toast.success("API key removed — using username and password")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove API key")
    }
  }

  const handleTestConnection = async () => {
    try {
      const result = await testConnection.mutateAsync({
        url: dispatcharr.url || undefined,
        username: dispatcharr.username || undefined,
        password: dispatcharr.password || undefined,
        api_key: dispatcharr.api_key || undefined,
      })
      if (result.success) {
        const via = result.auth_method === "api_key" ? " via API key" : ""
        toast.success(`Connected${via}! ${result.account_count} accounts, ${result.group_count} groups, ${result.channel_count} channels`)
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
                  <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <TestTube className="h-4 w-4 mr-1" />
                )}
                Test
              </Button>
              {dispatcharrStatus.data?.connected ? (
                <Badge variant="success" className="gap-1">
                  <CircleCheckBig className="h-3 w-3" /> Connected
                </Badge>
              ) : dispatcharrStatus.data?.configured && dispatcharrStatus.data?.error ? (
                <Badge variant="destructive" className="gap-1" title={dispatcharrStatus.data.error}>
                  <TriangleAlert className="h-3 w-3" /> Error
                </Badge>
              ) : dispatcharrStatus.data?.configured ? (
                <Badge variant="warning" className="gap-1">
                  <CircleX className="h-3 w-3" /> Disconnected
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
              icon={<TriangleAlert className="h-4 w-4 text-destructive" />}
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

          {/* API key (#817): the preferred credential. Username and password
              stay as the fallback for Dispatcharr < 0.20.0 and for anyone
              who has not minted a key yet. */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="dispatcharr-api-key">API Key (recommended)</Label>
              {initial.api_key && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRemoveApiKey}
                  disabled={updateDispatcharr.isPending}
                >
                  Remove saved key
                </Button>
              )}
            </div>
            <Input
              id="dispatcharr-api-key"
              type="password"
              value={dispatcharr.api_key ?? ""}
              onChange={(e) => setDispatcharr({ ...dispatcharr, api_key: e.target.value })}
              placeholder={initial.api_key ? "Leave blank to keep current" : "Paste a key from your Dispatcharr profile"}
            />
            <p className="text-xs text-muted-foreground">
              Generate one on your Dispatcharr profile page (Dispatcharr 0.20.0 or later). When a key is saved,
              the username and password below are not used.
            </p>
            {!initial.api_key && initial.username && initial.password && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleAdoptApiKey}
                disabled={adoptApiKey.isPending}
              >
                {adoptApiKey.isPending ? (
                  <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <KeyRound className="h-4 w-4 mr-1" />
                )}
                Use an API key instead
              </Button>
            )}
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
