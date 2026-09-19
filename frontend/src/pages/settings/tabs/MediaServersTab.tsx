import { useState } from "react"
import { toast } from "sonner"
import { LoaderCircle, TestTube, CircleCheckBig, CircleX, Plus, Trash2 } from "lucide-react"
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
  usePlexSettings,
  useUpdatePlexSettings,
  useTestPlexConnection,
  usePlexDvrs,
} from "@/hooks/useSettings"
import type { ChannelsDVRServer, ChannelsDVRSettings, EmbySettings, JellyfinSettings, MediaServerEntry, PlexServer, PlexSettings } from "@/api/settings"
import { useChannelProfiles } from "@/hooks/useDispatcharr"

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

type MediaServerTestInput = {
  url?: string
  username?: string
  password?: string
  api_key?: string
}

const EMPTY_MEDIA_SERVER: MediaServerEntry = {
  name: "",
  url: null,
  username: null,
  password: null,
  api_key: null,
}

interface MediaServerRowProps {
  title: string
  urlPlaceholder: string
  index: number
  server: MediaServerEntry
  testing: boolean
  onChange: (server: MediaServerEntry) => void
  onRemove: () => void
  removable: boolean
  onTest: (data: MediaServerTestInput) => Promise<MediaServerTestResponse>
}

function MediaServerRow({
  title,
  urlPlaceholder,
  index,
  server,
  testing,
  onChange,
  onRemove,
  removable,
  onTest,
}: MediaServerRowProps) {
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const idPrefix = `${title.toLowerCase()}-${index}`

  const handleTest = async () => {
    try {
      setTestResult(null)
      // Masked secrets ("********") pass through — the backend resolves
      // them against the saved server matching this URL.
      const result = await onTest({
        url: server.url || undefined,
        username: server.username || undefined,
        password: server.password || undefined,
        api_key: server.api_key || undefined,
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
    <div className="rounded-lg border p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <Input
          className="max-w-56"
          value={server.name ?? ""}
          onChange={(e) => onChange({ ...server, name: e.target.value })}
          placeholder={`Server ${index + 1} name (optional)`}
        />
        <div className="flex items-center gap-2">
          <Button onClick={handleTest} variant="outline" size="sm" disabled={testing || !server.url}>
            {testing ? (
              <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <TestTube className="h-4 w-4 mr-1" />
            )}
            Test
          </Button>
          {removable && (
            <Button onClick={onRemove} variant="outline" size="sm">
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      {testResult && (
        testResult.success ? (
          <Badge variant="success" className="gap-1">
            <CircleCheckBig className="h-3 w-3" /> {testResult.message}
          </Badge>
        ) : (
          <Badge variant="destructive" className="gap-1">
            <CircleX className="h-3 w-3" /> {testResult.message}
          </Badge>
        )
      )}

      {/* URL */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-url`}>URL</Label>
        <Input
          id={`${idPrefix}-url`}
          value={server.url ?? ""}
          onChange={(e) => onChange({ ...server, url: e.target.value })}
          placeholder={urlPlaceholder}
        />
      </div>

      {/* API Key (preferred) */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-api-key`}>API Key</Label>
        <Input
          id={`${idPrefix}-api-key`}
          type="password"
          value={server.api_key ?? ""}
          onChange={(e) => onChange({ ...server, api_key: e.target.value })}
          placeholder="Leave as-is to keep current"
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
            value={server.username ?? ""}
            onChange={(e) => onChange({ ...server, username: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-password`}>Password</Label>
          <Input
            id={`${idPrefix}-password`}
            type="password"
            value={server.password ?? ""}
            onChange={(e) => onChange({ ...server, password: e.target.value })}
            placeholder="Leave as-is to keep current"
          />
        </div>
      </div>
    </div>
  )
}

interface MediaServerCardProps {
  title: string
  urlPlaceholder: string
  initial: MediaServerSettings
  saving: boolean
  testing: boolean
  onSave: (data: Partial<MediaServerSettings>) => Promise<unknown>
  onTest: (data: MediaServerTestInput) => Promise<MediaServerTestResponse>
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
  const [enabled, setEnabled] = useState(initial.enabled)
  const [servers, setServers] = useState<MediaServerEntry[]>(
    initial.servers.length > 0 ? initial.servers : [{ ...EMPTY_MEDIA_SERVER }]
  )

  const handleSave = async () => {
    try {
      // Drop rows the user added but never filled in
      await onSave({ enabled, servers: servers.filter((s) => s.url) })
      toast.success(`${title} settings saved`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          <Button
            onClick={() => setServers([...servers, { ...EMPTY_MEDIA_SERVER }])}
            variant="outline"
            size="sm"
          >
            <Plus className="h-4 w-4 mr-1" /> Add Server
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable */}
        <div className="flex items-center gap-2">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          <Label>Enable {title} Integration</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          Every server listed below refreshes its guide in the background after each generation.
        </p>

        {servers.map((server, i) => (
          <MediaServerRow
            key={i}
            title={title}
            urlPlaceholder={urlPlaceholder}
            index={i}
            server={server}
            testing={testing}
            onChange={(updated) => setServers(servers.map((s, j) => (j === i ? updated : s)))}
            onRemove={() => setServers(servers.filter((_, j) => j !== i))}
            removable={servers.length > 1}
            onTest={onTest}
          />
        ))}

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

const EMPTY_SERVER: ChannelsDVRServer = {
  name: "",
  url: null,
  source_name: null,
  lineup_id: null,
}

interface ServerRowProps {
  index: number
  server: ChannelsDVRServer
  onChange: (server: ChannelsDVRServer) => void
  onRemove: () => void
  removable: boolean
}

function ChannelsDVRServerRow({ index, server, onChange, onRemove, removable }: ServerRowProps) {
  const testChannelsDVR = useTestChannelsDVRConnection()
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const { data: sourcesData, isFetching: sourcesLoading } = useChannelsDVRSources(server.url)
  const { data: lineupsData, isFetching: lineupsLoading } = useChannelsDVRLineups(server.url)

  const idPrefix = `channelsdvr-${index}`
  const noUrl = !server.url

  const handleTest = async () => {
    try {
      setTestResult(null)
      const result = await testChannelsDVR.mutateAsync({
        url: server.url || undefined,
        source_name: server.source_name || undefined,
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
    <div className="rounded-lg border p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-1">
          <Input
            id={`${idPrefix}-name`}
            className="max-w-56"
            value={server.name ?? ""}
            onChange={(e) => onChange({ ...server, name: e.target.value })}
            placeholder={`Server ${index + 1} name (optional)`}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={handleTest} variant="outline" size="sm" disabled={testChannelsDVR.isPending || noUrl}>
            {testChannelsDVR.isPending ? (
              <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <TestTube className="h-4 w-4 mr-1" />
            )}
            Test
          </Button>
          {removable && (
            <Button onClick={onRemove} variant="outline" size="sm">
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      {testResult && (
        testResult.success ? (
          <Badge variant="success" className="gap-1">
            <CircleCheckBig className="h-3 w-3" /> {testResult.message}
          </Badge>
        ) : (
          <Badge variant="destructive" className="gap-1">
            <CircleX className="h-3 w-3" /> {testResult.message}
          </Badge>
        )
      )}

      {/* URL */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-url`}>URL</Label>
        <Input
          id={`${idPrefix}-url`}
          value={server.url ?? ""}
          onChange={(e) => onChange({ ...server, url: e.target.value })}
          placeholder="http://channelsdvr:8089"
        />
      </div>

      {/* Source Name (discovered list) */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-source-name`}>M3U Source</Label>
        {(() => {
          const sources = sourcesData?.sources ?? []
          const sourcesError = sourcesData && !sourcesData.success
            ? sourcesData.error : null
          const saved = server.source_name ?? ""
          const savedMissing = saved && sources.length > 0 && !sources.includes(saved)
          return (
            <>
              <Select
                id={`${idPrefix}-source-name`}
                value={saved}
                onChange={(e) => onChange({ ...server, source_name: e.target.value })}
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
        <Label htmlFor={`${idPrefix}-lineup-id`}>XMLTV Lineup (EPG)</Label>
        {(() => {
          const lineups = lineupsData?.lineups ?? []
          const lineupsError = lineupsData && !lineupsData.success
            ? lineupsData.error : null
          const saved = server.lineup_id ?? ""
          const savedMissing = saved && lineups.length > 0 && !lineups.some((l) => l.id === saved)
          return (
            <>
              <Select
                id={`${idPrefix}-lineup-id`}
                value={saved}
                onChange={(e) => onChange({ ...server, lineup_id: e.target.value })}
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
    </div>
  )
}

function ChannelsDVRForm({ initial }: { initial: ChannelsDVRSettings }) {
  const updateChannelsDVR = useUpdateChannelsDVRSettings()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [servers, setServers] = useState<ChannelsDVRServer[]>(
    initial.servers.length > 0 ? initial.servers : [{ ...EMPTY_SERVER }]
  )

  const handleSave = async () => {
    try {
      // Drop rows the user added but never filled in
      await updateChannelsDVR.mutateAsync({
        enabled,
        servers: servers.filter((s) => s.url),
      })
      toast.success("Channels DVR settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Channels DVR</CardTitle>
          <Button
            onClick={() => setServers([...servers, { ...EMPTY_SERVER }])}
            variant="outline"
            size="sm"
          >
            <Plus className="h-4 w-4 mr-1" /> Add Server
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable */}
        <div className="flex items-center gap-2">
          <Switch
            checked={enabled}
            onCheckedChange={setEnabled}
          />
          <Label>Enable Channels DVR Integration</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          Every server listed below refreshes its channels and guide in the background after each generation.
        </p>

        {servers.map((server, i) => (
          <ChannelsDVRServerRow
            key={i}
            index={i}
            server={server}
            onChange={(updated) => setServers(servers.map((s, j) => (j === i ? updated : s)))}
            onRemove={() => setServers(servers.filter((_, j) => j !== i))}
            removable={servers.length > 1}
          />
        ))}

        {/* Save button */}
        <SaveButton onClick={handleSave} pending={updateChannelsDVR.isPending} />
      </CardContent>
    </Card>
  )
}

function PlexCard() {
  const { data } = usePlexSettings()
  if (!data) return null
  return <PlexForm initial={data} />
}

const EMPTY_PLEX_SERVER: PlexServer = {
  name: "",
  url: null,
  token: null,
  dvr_id: null,
  device_key: null,
  channel_profile_id: null,
}

interface PlexServerRowProps {
  index: number
  server: PlexServer
  onChange: (server: PlexServer) => void
  onRemove: () => void
  removable: boolean
}

function PlexServerRow({ index, server, onChange, onRemove, removable }: PlexServerRowProps) {
  const testPlex = useTestPlexConnection()
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const { data: dvrsData, isFetching: dvrsLoading } = usePlexDvrs(server.url, server.token)
  const { data: channelProfiles = [] } = useChannelProfiles()

  const idPrefix = `plex-${index}`
  const noUrl = !server.url
  const noToken = !server.token

  const handleTest = async () => {
    try {
      setTestResult(null)
      const result = await testPlex.mutateAsync({
        url: server.url || undefined,
        token: server.token || undefined,
      })
      if (result.success) {
        setTestResult({
          success: true,
          message: `Connected to Plex (${result.dvr_count ?? 0} DVR${result.dvr_count === 1 ? "" : "s"})`,
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

  const devices = (dvrsData?.dvrs ?? []).flatMap((dvr) =>
    dvr.devices.map((device) => ({ dvr, device }))
  )
  const selectedValue = server.dvr_id && server.device_key ? `${server.dvr_id}::${server.device_key}` : ""
  const savedMissing =
    selectedValue && devices.length > 0 &&
    !devices.some((d) => `${d.dvr.key}::${d.device.key}` === selectedValue)

  return (
    <div className="rounded-lg border p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-1">
          <Input
            id={`${idPrefix}-name`}
            className="max-w-56"
            value={server.name ?? ""}
            onChange={(e) => onChange({ ...server, name: e.target.value })}
            placeholder={`Server ${index + 1} name (optional)`}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={handleTest} variant="outline" size="sm" disabled={testPlex.isPending || noUrl || noToken}>
            {testPlex.isPending ? (
              <LoaderCircle className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <TestTube className="h-4 w-4 mr-1" />
            )}
            Test
          </Button>
          {removable && (
            <Button onClick={onRemove} variant="outline" size="sm">
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      {testResult && (
        testResult.success ? (
          <Badge variant="success" className="gap-1">
            <CircleCheckBig className="h-3 w-3" /> {testResult.message}
          </Badge>
        ) : (
          <Badge variant="destructive" className="gap-1">
            <CircleX className="h-3 w-3" /> {testResult.message}
          </Badge>
        )
      )}

      {/* URL */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-url`}>URL</Label>
        <Input
          id={`${idPrefix}-url`}
          value={server.url ?? ""}
          onChange={(e) => onChange({ ...server, url: e.target.value, dvr_id: null, device_key: null })}
          placeholder="http://plex:32400"
        />
      </div>

      {/* Token */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-token`}>Plex Token</Label>
        <Input
          id={`${idPrefix}-token`}
          type="password"
          value={server.token ?? ""}
          onChange={(e) => onChange({ ...server, token: e.target.value })}
          placeholder="Leave as-is to keep current"
        />
        <p className="text-xs text-muted-foreground">
          Sent as <code className="px-1 rounded bg-muted">X-Plex-Token</code>. See{" "}
          <a
            href="https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            finding your token
          </a>.
        </p>
      </div>

      {/* DVR / Device (discovered list) */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-device`}>DVR / Device</Label>
        {(() => {
          const devicesError = dvrsData && !dvrsData.success ? dvrsData.error : null
          return (
            <>
              <Select
                id={`${idPrefix}-device`}
                value={selectedValue}
                onChange={(e) => {
                  const [dvrId, deviceKey] = e.target.value.split("::")
                  const picked = devices.find((d) => d.dvr.key === dvrId && d.device.key === deviceKey)
                  const hint = picked?.device.profile_hint
                  const matchedProfile = hint
                    ? channelProfiles.find((p) => p.name.toLowerCase() === hint.toLowerCase())
                    : undefined
                  onChange({
                    ...server,
                    dvr_id: dvrId || null,
                    device_key: deviceKey || null,
                    channel_profile_id: matchedProfile ? matchedProfile.id : server.channel_profile_id,
                  })
                }}
                disabled={noUrl || noToken || dvrsLoading}
              >
                <option value="">
                  {noUrl || noToken
                    ? "— Set URL and token first —"
                    : dvrsLoading
                    ? "Loading DVRs…"
                    : devices.length === 0
                    ? "— No DVRs discovered —"
                    : "— Select a DVR/device —"}
                </option>
                {devices.map(({ dvr, device }) => (
                  <option key={`${dvr.key}::${device.key}`} value={`${dvr.key}::${device.key}`}>
                    {device.profile_hint || device.uri || device.key}
                    {" "}({device.channel_count} enabled)
                  </option>
                ))}
                {savedMissing && (
                  <option value={selectedValue}>{selectedValue} (not found on server)</option>
                )}
              </Select>
              <p className="text-xs text-muted-foreground">
                Discovered from <code className="px-1 rounded bg-muted">GET /livetv/dvrs</code>. A device with no
                profile suffix (e.g. plain <code className="px-1 rounded bg-muted">/hdhr</code>) pulls channels from
                every Dispatcharr profile — pick it only if that's intentional.
              </p>
              {devicesError && (
                <p className="text-xs text-destructive">Couldn't load DVRs: {devicesError}</p>
              )}
            </>
          )
        })()}
      </div>

      {/* Dispatcharr channel profile (scopes which channels get pushed to this device) */}
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-profile`}>Dispatcharr Channel Profile</Label>
        <Select
          id={`${idPrefix}-profile`}
          value={server.channel_profile_id != null ? String(server.channel_profile_id) : ""}
          onChange={(e) => {
            const raw = e.target.value
            const profile = channelProfiles.find((p) => String(p.id) === raw)
            onChange({ ...server, channel_profile_id: profile ? profile.id : null })
          }}
        >
          <option value="">— Unscoped (all Teamarr channels) —</option>
          {channelProfiles.map((profile) => (
            <option key={profile.id} value={String(profile.id)}>
              {profile.name}
            </option>
          ))}
        </Select>
        <p className="text-xs text-muted-foreground">
          If this device's HDHomeRun URI is scoped to one Dispatcharr profile, pick the
          matching profile so only that profile's channels are pushed to it — otherwise
          leave unscoped.
        </p>
      </div>
    </div>
  )
}

function PlexForm({ initial }: { initial: PlexSettings }) {
  const updatePlex = useUpdatePlexSettings()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [servers, setServers] = useState<PlexServer[]>(
    initial.servers.length > 0 ? initial.servers : [{ ...EMPTY_PLEX_SERVER }]
  )

  const handleSave = async () => {
    try {
      // Drop rows the user added but never filled in
      await updatePlex.mutateAsync({
        enabled,
        servers: servers.filter((s) => s.url),
      })
      toast.success("Plex settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Plex</CardTitle>
          <Button
            onClick={() => setServers([...servers, { ...EMPTY_PLEX_SERVER }])}
            variant="outline"
            size="sm"
          >
            <Plus className="h-4 w-4 mr-1" /> Add Server
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable */}
        <div className="flex items-center gap-2">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          <Label>Enable Plex Integration</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          After each generation, reloads the guide and syncs enabled channels for the matched
          DVR/device. Channels already enabled on the same device that aren't Teamarr's are
          preserved.
        </p>

        {servers.map((server, i) => (
          <PlexServerRow
            key={i}
            index={i}
            server={server}
            onChange={(updated) => setServers(servers.map((s, j) => (j === i ? updated : s)))}
            onRemove={() => setServers(servers.filter((_, j) => j !== i))}
            removable={servers.length > 1}
          />
        ))}

        {/* Save button */}
        <SaveButton onClick={handleSave} pending={updatePlex.isPending} />
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
      <PlexCard />
    </>
  )
}
