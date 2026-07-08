import { useState } from "react"
import { toast } from "sonner"
import { Loader2, TestTube, CheckCircle, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import {
  useEmbySettings,
  useUpdateEmbySettings,
  useTestEmbyConnection,
  useJellyfinSettings,
  useUpdateJellyfinSettings,
  useTestJellyfinConnection,
  useChannelsDVRSettings,
  useUpdateChannelsDVRSettings,
  useTestChannelsDVRConnection,
  useChannelsDVRSources,
  useChannelsDVRLineups,
} from "@/hooks/useSettings"
import type { ChannelsDVRSettings, EmbySettings, JellyfinSettings } from "@/api/settings"

interface TestResult {
  success: boolean
  message: string
}

// Emby and Jellyfin settings share the exact same shape
type MediaServerSettings = EmbySettings | JellyfinSettings

interface MediaServerTestResponse {
  success: boolean
  server_name?: string | null
  server_version?: string | null
  error?: string | null
}

interface MediaServerCardProps {
  title: string
  urlPlaceholder: string
  initial: MediaServerSettings
  saving: boolean
  testing: boolean
  onSave: (data: Partial<MediaServerSettings>) => Promise<unknown>
  onTest: (data: {
    url?: string
    username?: string
    password?: string
    api_key?: string
  }) => Promise<MediaServerTestResponse>
}

function MediaServerCard({
  title,
  urlPlaceholder,
  initial,
  saving,
  testing,
  onSave,
  onTest,
}: MediaServerCardProps) {
  const [form, setForm] = useState<Partial<MediaServerSettings>>({
    enabled: initial.enabled,
    url: initial.url,
    username: initial.username,
    password: "", // Don't show masked password
    api_key: "", // Don't show masked API key
  })
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const idPrefix = title.toLowerCase()

  const handleSave = async () => {
    try {
      const data: Partial<MediaServerSettings> = {
        enabled: form.enabled,
        url: form.url,
        username: form.username,
      }
      if (form.password) {
        data.password = form.password
      }
      if (form.api_key) {
        data.api_key = form.api_key
      }
      await onSave(data)
      toast.success(`${title} settings saved`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTest = async () => {
    try {
      setTestResult(null)
      const result = await onTest({
        url: form.url || undefined,
        username: form.username || undefined,
        password: form.password || undefined,
        api_key: form.api_key || undefined,
      })
      if (result.success) {
        setTestResult({
          success: true,
          message: `Connected to ${result.server_name || title} (v${result.server_version || "unknown"})`,
        })
      } else {
        setTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>{title}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleTest} variant="outline" size="sm" disabled={testing}>
              {testing ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <TestTube className="h-4 w-4 mr-1" />
              )}
              Test
            </Button>
            {testResult && (
              testResult.success ? (
                <Badge variant="success" className="gap-1">
                  <CheckCircle className="h-3 w-3" /> {testResult.message}
                </Badge>
              ) : (
                <Badge variant="destructive" className="gap-1">
                  <XCircle className="h-3 w-3" /> {testResult.message}
                </Badge>
              )
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable */}
        <div className="flex items-center gap-2">
          <Switch
            checked={form.enabled ?? false}
            onCheckedChange={(checked) => setForm({ ...form, enabled: checked })}
          />
          <Label>Enable {title} Integration</Label>
        </div>

        {/* URL */}
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-url`}>URL</Label>
          <Input
            id={`${idPrefix}-url`}
            value={form.url ?? ""}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            placeholder={urlPlaceholder}
          />
        </div>

        {/* API Key (preferred) */}
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-api-key`}>API Key</Label>
          <Input
            id={`${idPrefix}-api-key`}
            type="password"
            value={form.api_key ?? ""}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            placeholder="Leave blank to keep current"
          />
          <p className="text-xs text-muted-foreground">
            Recommended. Generate in {title} Dashboard &rarr; API Keys. If set, username/password are ignored.
          </p>
        </div>

        {/* Username/Password (fallback) */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-username`}>Username</Label>
            <Input
              id={`${idPrefix}-username`}
              value={form.username ?? ""}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              disabled={!!form.api_key}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-password`}>Password</Label>
            <Input
              id={`${idPrefix}-password`}
              type="password"
              value={form.password ?? ""}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="Leave blank to keep current"
              disabled={!!form.api_key}
            />
          </div>
        </div>

        {/* Save button */}
        <SaveButton onClick={handleSave} pending={saving} />
      </CardContent>
    </Card>
  )
}

function EmbyCard() {
  const { data } = useEmbySettings()
  const updateEmby = useUpdateEmbySettings()
  const testEmby = useTestEmbyConnection()
  if (!data) return null
  return (
    <MediaServerCard
      title="Emby"
      urlPlaceholder="http://emby:8096"
      initial={data}
      saving={updateEmby.isPending}
      testing={testEmby.isPending}
      onSave={(d) => updateEmby.mutateAsync(d)}
      onTest={(d) => testEmby.mutateAsync(d)}
    />
  )
}

function JellyfinCard() {
  const { data } = useJellyfinSettings()
  const updateJellyfin = useUpdateJellyfinSettings()
  const testJellyfin = useTestJellyfinConnection()
  if (!data) return null
  return (
    <MediaServerCard
      title="Jellyfin"
      urlPlaceholder="http://jellyfin:8096"
      initial={data}
      saving={updateJellyfin.isPending}
      testing={testJellyfin.isPending}
      onSave={(d) => updateJellyfin.mutateAsync(d)}
      onTest={(d) => testJellyfin.mutateAsync(d)}
    />
  )
}

function ChannelsDVRCard() {
  const { data } = useChannelsDVRSettings()
  if (!data) return null
  return <ChannelsDVRForm initial={data} />
}

function ChannelsDVRForm({ initial }: { initial: ChannelsDVRSettings }) {
  const updateChannelsDVR = useUpdateChannelsDVRSettings()
  const testChannelsDVR = useTestChannelsDVRConnection()
  const [channelsdvr, setChannelsDVR] = useState<Partial<ChannelsDVRSettings>>({
    enabled: initial.enabled,
    url: initial.url,
    source_name: initial.source_name,
    lineup_id: initial.lineup_id,
  })
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const { data: sourcesData, isFetching: sourcesLoading } =
    useChannelsDVRSources(channelsdvr.url || initial.url)
  const { data: lineupsData, isFetching: lineupsLoading } =
    useChannelsDVRLineups(channelsdvr.url || initial.url)

  const handleSave = async () => {
    try {
      const data: Partial<ChannelsDVRSettings> = {
        enabled: channelsdvr.enabled,
        url: channelsdvr.url,
        source_name: channelsdvr.source_name,
        lineup_id: channelsdvr.lineup_id,
      }
      await updateChannelsDVR.mutateAsync(data)
      toast.success("Channels DVR settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  const handleTest = async () => {
    try {
      setTestResult(null)
      const result = await testChannelsDVR.mutateAsync({
        url: channelsdvr.url || undefined,
        source_name: channelsdvr.source_name || undefined,
      })
      if (result.success) {
        const versionPart = result.server_version ? ` (v${result.server_version})` : ""
        const sourcePart = result.source_name ? ` — source '${result.source_name}' OK` : ""
        setTestResult({
          success: true,
          message: `Connected to Channels DVR${versionPart}${sourcePart}`,
        })
      } else {
        setTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Channels DVR</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleTest} variant="outline" size="sm" disabled={testChannelsDVR.isPending}>
              {testChannelsDVR.isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              ) : (
                <TestTube className="h-4 w-4 mr-1" />
              )}
              Test
            </Button>
            {testResult && (
              testResult.success ? (
                <Badge variant="success" className="gap-1">
                  <CheckCircle className="h-3 w-3" /> {testResult.message}
                </Badge>
              ) : (
                <Badge variant="destructive" className="gap-1">
                  <XCircle className="h-3 w-3" /> {testResult.message}
                </Badge>
              )
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable */}
        <div className="flex items-center gap-2">
          <Switch
            checked={channelsdvr.enabled ?? false}
            onCheckedChange={(checked) => setChannelsDVR({ ...channelsdvr, enabled: checked })}
          />
          <Label>Enable Channels DVR Integration</Label>
        </div>

        {/* URL */}
        <div className="space-y-2">
          <Label htmlFor="channelsdvr-url">URL</Label>
          <Input
            id="channelsdvr-url"
            value={channelsdvr.url ?? ""}
            onChange={(e) => setChannelsDVR({ ...channelsdvr, url: e.target.value })}
            placeholder="http://channelsdvr:8089"
          />
        </div>

        {/* Source Name (discovered list) */}
        <div className="space-y-2">
          <Label htmlFor="channelsdvr-source-name">M3U Source</Label>
          {(() => {
            const sources = sourcesData?.sources ?? []
            const sourcesError = sourcesData && !sourcesData.success
              ? sourcesData.error : null
            const saved = channelsdvr.source_name ?? ""
            const savedMissing = saved && sources.length > 0 && !sources.includes(saved)
            const noUrl = !channelsdvr.url
            return (
              <>
                <Select
                  id="channelsdvr-source-name"
                  value={saved}
                  onChange={(e) => setChannelsDVR({ ...channelsdvr, source_name: e.target.value })}
                  disabled={noUrl || sourcesLoading}
                >
                  <option value="">
                    {noUrl
                      ? "— Set URL first —"
                      : sourcesLoading
                      ? "Loading sources…"
                      : sources.length === 0
                      ? "— No sources discovered —"
                      : "— Select an M3U source —"}
                  </option>
                  {sources.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                  {savedMissing && (
                    <option value={saved}>{saved} (not found on server)</option>
                  )}
                </Select>
                <p className="text-xs text-muted-foreground">
                  Discovered from <code className="px-1 rounded bg-muted">GET /devices</code> (Provider = m3u).
                  Refresh hits <code className="px-1 rounded bg-muted">POST /providers/m3u/sources/&lt;name&gt;/refresh</code> after each generation.
                </p>
                {sourcesError && (
                  <p className="text-xs text-destructive">Couldn't load sources: {sourcesError}</p>
                )}
              </>
            )
          })()}
        </div>

        {/* XMLTV Lineup (drives EPG refresh) */}
        <div className="space-y-2">
          <Label htmlFor="channelsdvr-lineup-id">XMLTV Lineup (EPG)</Label>
          {(() => {
            const lineups = lineupsData?.lineups ?? []
            const lineupsError = lineupsData && !lineupsData.success
              ? lineupsData.error : null
            const saved = channelsdvr.lineup_id ?? ""
            const savedMissing = saved && lineups.length > 0 && !lineups.some((l) => l.id === saved)
            const noUrl = !channelsdvr.url
            return (
              <>
                <Select
                  id="channelsdvr-lineup-id"
                  value={saved}
                  onChange={(e) => setChannelsDVR({ ...channelsdvr, lineup_id: e.target.value })}
                  disabled={noUrl || lineupsLoading}
                >
                  <option value="">
                    {noUrl
                      ? "— Set URL first —"
                      : lineupsLoading
                      ? "Loading lineups…"
                      : lineups.length === 0
                      ? "— No lineups discovered —"
                      : "— Select an XMLTV lineup —"}
                  </option>
                  {lineups.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name === l.id ? l.id : `${l.name} (${l.id})`}
                    </option>
                  ))}
                  {savedMissing && (
                    <option value={saved}>{saved} (not found on server)</option>
                  )}
                </Select>
                <p className="text-xs text-muted-foreground">
                  Discovered from <code className="px-1 rounded bg-muted">GET /dvr/lineups</code>.
                  Refresh hits <code className="px-1 rounded bg-muted">PUT /dvr/lineups/&lt;id&gt;</code> so the EPG actually updates.
                  Without this the M3U refresh leaves the guide stale.
                </p>
                {lineupsError && (
                  <p className="text-xs text-destructive">Couldn't load lineups: {lineupsError}</p>
                )}
              </>
            )
          })()}
        </div>

        {/* Save button */}
        <SaveButton onClick={handleSave} pending={updateChannelsDVR.isPending} />
      </CardContent>
    </Card>
  )
}

export function MediaServersTab() {
  return (
    <>
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Media Servers</h2>
        <p className="text-sm text-muted-foreground">
          Connect media servers to auto-refresh their live TV guides after EPG generation.
        </p>
      </div>

      <EmbyCard />
      <JellyfinCard />
      <ChannelsDVRCard />
    </>
  )
}
