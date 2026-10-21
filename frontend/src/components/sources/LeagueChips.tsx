import { useLayoutEffect, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { RichTooltip } from "@/components/ui/rich-tooltip"
import type { LeagueShare } from "@/api/types"

// Never show fewer than this many chips, even if they have to wrap: the
// reader should always see the top of the breakdown without hovering.
const MIN_CHIPS = 3
const GAP_PX = 4
const OVERFLOW_PX = 36

interface LeagueChipsProps {
  shares: LeagueShare[]
  runAt: string | null
  formatDateTime: (value: string) => string
  onPick?: (league: string) => void
}

/**
 * A source's last-run league evidence as `NHL 97` chips (#1110): as many
 * whole chips as the cell is wide, then `+N`, the full breakdown on hover.
 * The number is the league's share of the source's *matched* streams, so a
 * single-league source reads 100 whatever its coverage.
 */
export function LeagueChips({ shares, runAt, formatDateTime, onPick }: LeagueChipsProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const measureRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(shares.length)

  useLayoutEffect(() => {
    const container = containerRef.current
    const measure = measureRef.current
    if (!container || !measure) return
    const compute = () => {
      const width = container.clientWidth
      const chips = Array.from(measure.children) as HTMLElement[]
      let used = 0
      let fit = 0
      for (let i = 0; i < chips.length; i++) {
        const w = chips[i].offsetWidth + (i ? GAP_PX : 0)
        const reserve = i + 1 < chips.length ? OVERFLOW_PX + GAP_PX : 0
        if (used + w + reserve > width && fit >= MIN_CHIPS) break
        used += w
        fit++
      }
      setVisible(Math.max(Math.min(fit, chips.length), Math.min(MIN_CHIPS, chips.length)))
    }
    compute()
    const observer = new ResizeObserver(compute)
    observer.observe(container)
    return () => observer.disconnect()
  }, [shares])

  if (shares.length === 0) {
    return (
      <span className="text-[0.65rem] text-muted-foreground italic" title={runAt ? `Nothing matched in the last run (${formatDateTime(runAt)})` : "No run yet"}>
        no matches yet
      </span>
    )
  }

  const chip = (s: LeagueShare, key: string) => (
    <Badge
      key={key}
      variant="secondary"
      className={`text-[0.65rem] whitespace-nowrap ${onPick ? "cursor-pointer hover:bg-secondary/60" : ""}`}
      onClick={onPick ? (e) => { e.stopPropagation(); onPick(s.league) } : undefined}
    >
      {s.display_name} <span className="ml-1 font-normal text-muted-foreground">{Math.round(s.share * 100)}</span>
    </Badge>
  )

  const hidden = shares.length - visible
  return (
    <RichTooltip
      side="top"
      content={
        <div className="space-y-1 text-xs">
          {shares.map((s) => (
            <div key={s.league} className="flex justify-between gap-4">
              <span>{s.display_name}<span className="text-muted-foreground"> · {s.sport_display_name}</span></span>
              <span className="tabular-nums">{s.count} · {Math.round(s.share * 100)}%</span>
            </div>
          ))}
          <div className="text-muted-foreground pt-1 border-t border-border">
            Share of this source's matched streams, not of all its streams.
            {runAt && <> Last run: {formatDateTime(runAt)}.</>}
          </div>
        </div>
      }
    >
      <div ref={containerRef} className="relative w-full">
        <div className="flex items-center gap-1 flex-wrap">
          {shares.slice(0, visible).map((s) => chip(s, s.league))}
          {hidden > 0 && (
            <Badge variant="outline" className="text-[0.65rem] whitespace-nowrap">+{hidden}</Badge>
          )}
        </div>
        {/* Measuring row: every chip, invisible, so the fit is computed from real widths. */}
        <div ref={measureRef} aria-hidden className="absolute left-0 top-0 flex items-center gap-1 whitespace-nowrap invisible pointer-events-none">
          {shares.map((s) => chip(s, `m-${s.league}`))}
        </div>
      </div>
    </RichTooltip>
  )
}
