import { useState } from "react"
import { GlobalDefaults } from "@/components/GlobalDefaults"
import { CustomLeaguesManager } from "@/pages/CustomLeagues"
import { useCustomLeagueCapability } from "@/hooks/useCustomLeagues"
import { SubNav, type SubNavItem } from "@/components/ui/sub-nav"

type Tile = "sportleague" | "soccer" | "teams" | "custom"

/**
 * Step 2 — Subscriptions. The sports and leagues you follow. A 4-tile in-page
 * sub-nav (Sport/League · Soccer · Teams · Custom Leagues) switches the content
 * below. GlobalDefaults stays mounted across the first three tiles so shared
 * subscription state is preserved.
 */
export function Subscriptions() {
  const [activeTile, setActiveTile] = useState<Tile>("sportleague")
  const capabilityQuery = useCustomLeagueCapability()
  const capability = capabilityQuery.data
  const premiumEnabled = !!capability?.enabled

  // Custom Leagues only appears once a TheSportsDB premium key is configured —
  // a locked tile read as confusing, so it's hidden entirely until usable.
  const tiles: SubNavItem[] = [
    { key: "sportleague", label: "Sport/League" },
    { key: "soccer", label: "Soccer" },
    { key: "teams", label: "Teams" },
    ...(premiumEnabled ? [{ key: "custom", label: "Custom Leagues" } as SubNavItem] : []),
  ]

  return (
    <div className="space-y-3">
      <div>
        <h1 className="text-xl font-bold">Subscriptions</h1>
      </div>

      <SubNav items={tiles} value={activeTile} onChange={(k) => setActiveTile(k as Tile)} />

      {activeTile === "custom" ? (
        <div className="space-y-3">
          <p className="text-sm italic text-muted-foreground">
            NOTE: Custom League support requires a Premium TheSportsDB API key
          </p>
          <CustomLeaguesManager capability={capability} />
        </div>
      ) : (
        <GlobalDefaults activeTile={activeTile} />
      )}
    </div>
  )
}
