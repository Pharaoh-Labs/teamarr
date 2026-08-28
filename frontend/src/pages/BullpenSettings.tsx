import { useState } from "react"
import { toast } from "sonner"
import { Spinner } from "@/components/ui/spinner"
import { Button } from "@/components/ui/button"
import { SaveButton } from "@/components/ui/save-button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useBullpenSettings, useUpdateBullpenSettings } from "@/hooks/useSettings"
import type { BullpenSettings as BullpenSettingsType } from "@/api/settings"

const PROVIDERS: { key: keyof BullpenSettingsType; label: string }[] = [
  { key: "espn_enabled", label: "ESPN" },
  { key: "bellmedia_enabled", label: "Bell Media (CFL)" },
  { key: "squiggle_enabled", label: "Squiggle (AFL)" },
  { key: "nascar_enabled", label: "NASCAR" },
  { key: "mlbstats_enabled", label: "MLB Stats" },
  { key: "hockeytech_enabled", label: "HockeyTech" },
  { key: "tsdb_enabled", label: "TheSportsDB (also unlocks premium tier)" },
]

export function BullpenSettings() {
  const { data, isLoading, error, refetch } = useBullpenSettings()
  const updateBullpen = useUpdateBullpenSettings()

  const [form, setForm] = useState<Partial<BullpenSettingsType> | null>(null)

  if (isLoading) {
    return <Spinner size="lg" className="py-12" />
  }

  if (error || !data) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-bold">Bullpen</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Error loading bullpen settings: {error?.message ?? "No data"}
            </p>
            <Button className="mt-4" onClick={() => refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const bullpen: Partial<BullpenSettingsType> = form ?? {
    enabled: data.enabled,
    api_key: "", // don't show masked key
    base_url: data.base_url,
    espn_enabled: data.espn_enabled,
    bellmedia_enabled: data.bellmedia_enabled,
    squiggle_enabled: data.squiggle_enabled,
    nascar_enabled: data.nascar_enabled,
    mlbstats_enabled: data.mlbstats_enabled,
    hockeytech_enabled: data.hockeytech_enabled,
    tsdb_enabled: data.tsdb_enabled,
  }

  const set = (patch: Partial<BullpenSettingsType>) => setForm({ ...bullpen, ...patch })

  const handleSave = async () => {
    try {
      const payload: Partial<BullpenSettingsType> = {
        enabled: bullpen.enabled,
        base_url: bullpen.base_url,
        espn_enabled: bullpen.espn_enabled,
        bellmedia_enabled: bullpen.bellmedia_enabled,
        squiggle_enabled: bullpen.squiggle_enabled,
        nascar_enabled: bullpen.nascar_enabled,
        mlbstats_enabled: bullpen.mlbstats_enabled,
        hockeytech_enabled: bullpen.hockeytech_enabled,
        tsdb_enabled: bullpen.tsdb_enabled,
      }
      if (bullpen.api_key) {
        payload.api_key = bullpen.api_key
      }
      await updateBullpen.mutateAsync(payload)
      toast.success("Bullpen settings saved")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save")
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Bullpen</h1>
        <p className="text-sm text-muted-foreground">
          Optional caching proxy (bullpen.direct) for provider upstreams. Off by default;
          this page has no sidebar entry and is only reachable at this URL.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <Switch
              checked={bullpen.enabled ?? false}
              onCheckedChange={(checked) => set({ enabled: checked })}
            />
            <Label>Enable bullpen proxy</Label>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bullpen-api-key">API Key</Label>
            <Input
              id="bullpen-api-key"
              type="password"
              value={bullpen.api_key ?? ""}
              onChange={(e) => set({ api_key: e.target.value })}
              placeholder="Leave blank to keep current"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="bullpen-base-url">Base URL</Label>
            <Input
              id="bullpen-base-url"
              value={bullpen.base_url ?? ""}
              onChange={(e) => set({ base_url: e.target.value })}
              placeholder="https://bullpen.direct"
            />
          </div>

          <SaveButton onClick={handleSave} pending={updateBullpen.isPending} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Providers</CardTitle>
          <CardDescription>
            Route each provider's requests through bullpen. Each toggle is independent and
            defaults to off.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {PROVIDERS.map(({ key, label }) => (
            <div key={key} className="flex items-center gap-2">
              <Switch
                checked={Boolean(bullpen[key])}
                onCheckedChange={(checked) => set({ [key]: checked })}
              />
              <Label>{label}</Label>
            </div>
          ))}

          <SaveButton onClick={handleSave} pending={updateBullpen.isPending} />
        </CardContent>
      </Card>
    </div>
  )
}
