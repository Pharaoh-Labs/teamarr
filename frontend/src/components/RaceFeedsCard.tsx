import { useState } from "react"
import { toast } from "sonner"
import { LoaderCircle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { RaceFeed, RaceFeedBehavior, RaceFeedKind } from "@/api/raceFeeds"
import {
  useBulkRaceFeedBehavior,
  useRaceFeeds,
  useRefreshRaceFeeds,
  useUpdateRaceFeed,
} from "@/hooks/useRaceFeeds"

const BEHAVIOR_LABEL: Record<RaceFeedBehavior, string> = {
  consolidate: "Own channel",
  separate: "Separate",
  ignore: "Ignore",
}

/**
 * Race Feeds (#245): per-league driver and feed-variant rows that ride the
 * exception-keyword engine. "Own channel" gives that driver's onboard (or the
 * pit-lane / tracker feed) its own channel per session; "Ignore" drops it.
 * Labels and match terms come from the provider roster and refresh with the
 * cache; only the behavior and on/off are the user's.
 */
export function RaceFeedsCard() {
  const [league, setLeague] = useState<string | undefined>(undefined)
  const feedsQuery = useRaceFeeds(league)
  const updateFeed = useUpdateRaceFeed()
  const bulk = useBulkRaceFeedBehavior()
  const refresh = useRefreshRaceFeeds()

  const data = feedsQuery.data
  const leagues = data?.leagues ?? []
  const activeLeague = league ?? leagues[0]
  const feeds = (data?.feeds ?? []).filter((f) => !activeLeague || f.league === activeLeague)
  const drivers = feeds.filter((f) => f.kind === "driver")
  const variants = feeds.filter((f) => f.kind === "variant")

  const setBehavior = (feed: RaceFeed, behavior: RaceFeedBehavior) =>
    updateFeed.mutate(
      { id: feed.id, behavior },
      { onError: () => toast.error(`Could not update ${feed.label}`) },
    )
  const setEnabled = (feed: RaceFeed, enabled: boolean) =>
    updateFeed.mutate(
      { id: feed.id, enabled },
      { onError: () => toast.error(`Could not update ${feed.label}`) },
    )
  const setAll = (kind: RaceFeedKind, behavior: RaceFeedBehavior) => {
    if (!activeLeague) return
    bulk.mutate(
      { league: activeLeague, kind, behavior },
      { onError: () => toast.error("Could not update feeds") },
    )
  }
  const doRefresh = () =>
    refresh.mutate(activeLeague, {
      onSuccess: (res) => toast.success(`Roster refreshed: ${res.total} feeds`),
      onError: () => toast.error("Roster refresh failed"),
    })

  const renderRows = (rows: RaceFeed[]) =>
    rows.map((feed) => (
      <TableRow key={feed.id} className={feed.enabled ? undefined : "opacity-50"}>
        <TableCell>
          <Checkbox
            checked={feed.enabled}
            onCheckedChange={(checked) => setEnabled(feed, !!checked)}
            aria-label={feed.enabled ? `Disable ${feed.label}` : `Enable ${feed.label}`}
          />
        </TableCell>
        <TableCell className="font-medium">{feed.label}</TableCell>
        <TableCell className="text-muted-foreground text-xs">{feed.match_term_list.join(", ")}</TableCell>
        <TableCell>
          <Select
            value={feed.behavior}
            onChange={(e) => setBehavior(feed, e.target.value as RaceFeedBehavior)}
            className="h-8"
            aria-label={`Behavior for ${feed.label}`}
          >
            <option value="consolidate">{BEHAVIOR_LABEL.consolidate}</option>
            <option value="separate">{BEHAVIOR_LABEL.separate}</option>
            <option value="ignore">{BEHAVIOR_LABEL.ignore}</option>
          </Select>
        </TableCell>
      </TableRow>
    ))

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>Race Feeds</CardTitle>
            <CardDescription>
              Driver onboards and alternate feeds (pit lane, tracker, timing) from the provider
              roster. <strong>Own channel</strong> gives a feed its own channel per session;{" "}
              <strong>Ignore</strong> drops it. Everything is off by default.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {leagues.length > 1 && (
              <Select
                value={activeLeague ?? ""}
                onChange={(e) => setLeague(e.target.value)}
                className="h-8"
                aria-label="League"
              >
                {leagues.map((lg) => (
                  <option key={lg} value={lg}>
                    {lg.toUpperCase()}
                  </option>
                ))}
              </Select>
            )}
            <Button size="sm" variant="outline" onClick={doRefresh} disabled={refresh.isPending}>
              {refresh.isPending ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              <span className="ml-1">Refresh roster</span>
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {feedsQuery.isLoading ? (
          <div className="text-muted-foreground text-sm">Loading…</div>
        ) : feeds.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            No roster yet. Refresh the cache (or click Refresh roster) after the first completed
            race of the season.
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-medium">Drivers ({drivers.length})</h4>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setAll("driver", "consolidate")}>
                  All own channel
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setAll("driver", "ignore")}>
                  All ignore
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="bg-muted">
                  <TableRow>
                    <TableHead className="w-12">On</TableHead>
                    <TableHead className="w-44">Driver</TableHead>
                    <TableHead>Matches</TableHead>
                    <TableHead className="w-40">Behavior</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>{renderRows(drivers)}</TableBody>
              </Table>
            </div>
            <h4 className="text-sm font-medium">Other feeds ({variants.length})</h4>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="bg-muted">
                  <TableRow>
                    <TableHead className="w-12">On</TableHead>
                    <TableHead className="w-44">Feed</TableHead>
                    <TableHead>Matches</TableHead>
                    <TableHead className="w-40">Behavior</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>{renderRows(variants)}</TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
