import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SaveButton } from "@/components/ui/save-button"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import type { ProxySettings } from "@/api/settings"
import { useProxyProviders, useProxySettings, useUpdateProxySettings } from "@/hooks/useSettings"

export function ProxyTab() {
  const { data, isLoading } = useProxySettings()
  const { data: providers = [] } = useProxyProviders()
  const updateProxy = useUpdateProxySettings()
  const [form, setForm] = useState<Partial<ProxySettings> | null>(null)
  const [clearUrl, setClearUrl] = useState(false)

  if (isLoading || !data) return <Spinner size="lg" className="py-12" />

  const proxy = form ?? { ...data, url: "" }
  const set = (patch: Partial<ProxySettings>) => setForm({ ...proxy, ...patch })
  const excluded = new Set(proxy.excluded_providers ?? [])

  const save = async () => {
    try {
      const payload: Partial<ProxySettings> = {
        enabled: proxy.enabled,
        user_agent: proxy.user_agent || null,
        excluded_providers: [...excluded],
      }
      if (proxy.url) payload.url = proxy.url
      else if (clearUrl) payload.url = null
      await updateProxy.mutateAsync(payload)
      setForm(null)
      setClearUrl(false)
      toast.success("Proxy settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save proxy settings")
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle>Provider SOCKS5 Proxy</CardTitle>
          <CardDescription>
            Routes provider API requests through SOCKS5. Media servers and Dispatcharr stay direct.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <Switch checked={proxy.enabled ?? false} onCheckedChange={(enabled) => set({ enabled })} />
            <Label>Enable proxy for providers</Label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="proxy-url">SOCKS5 URL</Label>
            <Input id="proxy-url" type="password" value={proxy.url ?? ""} placeholder="socks5://user:password@host:port" onChange={(event) => { set({ url: event.target.value }); setClearUrl(false) }} />
            {data.url && <Button type="button" variant="outline" size="sm" onClick={() => setClearUrl(!clearUrl)}>{clearUrl ? "Keep saved proxy URL" : "Clear saved proxy URL"}</Button>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="proxy-user-agent">User-Agent override (optional)</Label>
            <Input id="proxy-user-agent" value={proxy.user_agent ?? ""} onChange={(event) => set({ user_agent: event.target.value })} placeholder="Preserve each provider's default" />
          </div>
          <SaveButton onClick={save} pending={updateProxy.isPending} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Provider Exceptions</CardTitle>
          <CardDescription>All registered providers use the proxy by default. Disable an individual provider to keep it direct.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {providers.map((provider) => (
            <div key={provider} className="flex items-center gap-2">
              <Switch checked={!excluded.has(provider)} onCheckedChange={(enabled) => { const next = new Set(excluded); if (enabled) next.delete(provider); else next.add(provider); set({ excluded_providers: [...next] }) }} />
              <Label className="capitalize">{provider}</Label>
            </div>
          ))}
          <SaveButton onClick={save} pending={updateProxy.isPending} />
        </CardContent>
      </Card>
    </div>
  )
}
