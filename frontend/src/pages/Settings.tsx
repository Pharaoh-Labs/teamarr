import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Card, CardContent } from "@/components/ui/card"
import { SubNav } from "@/components/ui/sub-nav"
import { useSettings } from "@/hooks/useSettings"
import { GeneralTab } from "./settings/tabs/GeneralTab"
import { DispatcharrTab } from "./settings/tabs/DispatcharrTab"
import { MediaServersTab } from "./settings/tabs/MediaServersTab"
import { AdvancedTab } from "./settings/tabs/AdvancedTab"

type SettingsTab = "general" | "dispatcharr" | "media-servers" | "advanced"

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "dispatcharr", label: "Dispatcharr" },
  { id: "media-servers", label: "Media Servers" },
  { id: "advanced", label: "Advanced" },
]

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general")
  const { data: settings, isLoading, error, refetch } = useSettings()

  if (isLoading) {
    return (
      <Spinner size="lg" className="py-12" />
    )
  }

  if (error || !settings) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-bold">Settings</h1>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Error loading settings: {error?.message ?? "No data"}
            </p>
            <Button className="mt-4" onClick={() => refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div>
        <h1 className="text-xl font-bold">Settings</h1>
      </div>

      <SubNav
        items={TABS.map((t) => ({ key: t.id, label: t.label }))}
        value={activeTab}
        onChange={(k) => setActiveTab(k as SettingsTab)}
      />

      <div className="space-y-3 min-h-[400px]">
        {activeTab === "general" && <GeneralTab settings={settings} />}
        {activeTab === "dispatcharr" && <DispatcharrTab initial={settings.dispatcharr} />}
        {activeTab === "media-servers" && <MediaServersTab />}
        {activeTab === "advanced" && <AdvancedTab />}
      </div>
    </div>
  )
}
