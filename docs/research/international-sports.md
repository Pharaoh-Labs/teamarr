---
title: International Sports
parent: Research Notes
nav_order: 1
docs_version: "2.7.0"
---

# International Sports Research — Consolidated Findings

**Date:** 2026-02-14
**Epic:** `teamarrv2-ia2`
**Related Issues:** #122, #88, #100, #104
**Tiered Model Epic:** `teamarrv2-s9n`

## Provider Tier Model

- **Tier 1 (Free):** ESPN, HockeyTech, TSDB leagues with <10-12 teams (free key sufficient)
- **Tier 2 (BYOK):** TSDB premium leagues — user provides their own key ($80/year)

---

## 1. FIFA/UEFA International Soccer (`ia2.1`)

### Already Supported
World Cup (`fifa.world`), Women's World Cup (`wwc`), Euro (`uefa.euro`), Copa America (`copa-america`), CONCACAF Nations League (`cnl`), Gold Cup (`gold-cup`)

### New ESPN Leagues Available

| League | ESPN Slug | ID | Teams | Tier | Notes |
|--------|-----------|-----|-------|------|-------|
| WCQ - UEFA | `fifa.worldq.uefa` | 786 | 54 | 1 | **12 events Mar 2026** |
| WCQ - CONCACAF | `fifa.worldq.concacaf` | 788 | 32 | 1 | Active |
| WCQ - CONMEBOL | `fifa.worldq.conmebol` | 787 | 10 | 1 | Active |
| WCQ - CAF | `fifa.worldq.caf` | 790 | 54 | 1 | Active |
| WCQ - AFC | `fifa.worldq.afc` | 789 | 46 | 1 | Active |
| WCQ - OFC | `fifa.worldq.ofc` | 792 | 11 | 1 | Active |
| UEFA Nations League | `uefa.nations` | 2395 | 54 | 1 | **4 events Mar 2026** |
| Intl Friendlies | `fifa.friendly` | 3922 | 71 | 1 | **59 events Feb-Apr** |
| Africa Cup of Nations | `caf.nations` | 3908 | 24 | 1 | Between tournaments |
| AFC Asian Cup | `afc.asian.cup` | 20219 | 24 | 1 | Between tournaments |
| Olympics Men's Soccer | `fifa.olympics` | 3924 | 16 | 1 | Summer Olympics |
| Olympics Women's Soccer | `fifa.w.olympics` | 3925 | 12 | 1 | Summer Olympics |

**NOTE:** ESPN soccer uses dot-notation slugs (e.g., `fifa.worldq.uefa`), not hyphenated.

**Implementation:** All Tier 1. Straightforward schema additions. ESPN provider already handles soccer.

---

## 2. FIBA International Basketball (`ia2.2`)

### Already Supported
NBA, WNBA, G League, NCAAM, NCAAW, Unrivaled (TSDB)

### ESPN Coverage (15 total basketball leagues)

| League | ESPN Slug | ID | Teams | Tier | Notes |
|--------|-----------|-----|-------|------|-------|
| FIBA World Cup | `fiba` | 53 | 32 | 1 | Tournament years only (last: 2023) |
| Olympics Men's Basketball | `mens-olympics-basketball` | 3766 | 12 | 1 | Summer Olympics |
| Olympics Women's Basketball | `womens-olympics-basketball` | 3767 | 12 | 1 | Summer Olympics |
| NBL Australia | `nbl` | 55 | 10 | 1 | **Active season, live data** |

**NOT on ESPN:** EuroLeague, EuroCup, BCL, FIBA regional (Americas, Europe, Asia, Africa) — none exist. ESPN basketball is heavily US-centric.

**EuroLeague/European club basketball:** Would require TSDB premium (Tier 2) or a dedicated provider. Not available through any current Teamarr provider on the free tier.

---

## 3. Olympic Team Sports (`ia2.4`)

### Already Supported
Olympic Hockey Men/Women (`olymh`/`olywh`) — **live right now** for 2026 Milano Cortina

### ESPN Slug Pattern Warning
Slugs are **inconsistent across sports**:
- Hockey: `olympics-mens-ice-hockey` (prefix)
- Basketball: `mens-olympics-basketball` (infix)
- Soccer: `fifa.olympics` / `fifa.w.olympics` (dot-separated)
- Rugby: `282` / `283` (numeric IDs!)
- Golf: `mens-olympics-golf` / `womens-olympics-golf` (infix)
- Baseball: `olympics-baseball` (prefix)

### 2026 Winter Olympics (Milano Cortina)

| Sport | ESPN Slug | ID | Status |
|-------|-----------|-----|--------|
| Men's Ice Hockey | `hockey/olympics-mens-ice-hockey` | 20146 | **LIVE — already supported** |
| Women's Ice Hockey | `hockey/olympics-womens-ice-hockey` | 20147 | **LIVE — already supported** |
| Curling | N/A | N/A | **ESPN has NO curling sport at all** |

### Summer Olympics Pattern (from Paris 2024 data)

| Sport | ESPN Slug | ID | Teams | Tier |
|-------|-----------|-----|-------|------|
| Men's Basketball | `basketball/mens-olympics-basketball` | 3766 | 12 | 1 |
| Women's Basketball | `basketball/womens-olympics-basketball` | 3767 | 12 | 1 |
| Men's Soccer | `soccer/fifa.olympics` | 3924 | 16 | 1 |
| Women's Soccer | `soccer/fifa.w.olympics` | 3925 | 12 | 1 |
| Men's Rugby 7s | `rugby/282` | 10743 | 12 | 1 |
| Women's Rugby 7s | `rugby/283` | 10729 | 12 | 1 |
| Men's Golf | `golf/mens-olympics-golf` | 7003 | N/A | 1 |
| Women's Golf | `golf/womens-olympics-golf` | 7004 | N/A | 1 |
| Men's Baseball | `baseball/olympics-baseball` | 3706 | 8 | 1 |

**NOT on ESPN:** Handball, water polo, volleyball, field hockey, curling — no Olympic versions.

---

## 4. Handball (`ia2.5`)

### ESPN: No support
ESPN has no `handball` sport at all.

### TSDB: Excellent coverage (22 leagues, premium key required for full data)

| League | TSDB ID | Next Events (premium) | Tier |
|--------|---------|----------------------|------|
| EHF Champions League | 4980 | 20 | 2 |
| German Handball-Bundesliga | 4533 | 20 | 2 |
| French LNH Division 1 | 4536 | 20 | 2 |
| Danish Mens Handball League | 5135 | 20 | 2 |
| Spanish Liga ASOBAL | 4534 | 20 | 2 |
| Swedish Handbollsligan | 5136 | 20 | 2 |
| EHF European League | 5275 | ? | 2 |
| European Mens Handball Championship | 4894 | ? | 2 |

**Implementation:** All Tier 2. Requires `teamarrv2-s9n` (BYOK TSDB) to land first. TSDB provider already exists — just needs leagues added to schema with tier flag and user key support.

---

## 5. International Rugby (`ia2.6`)

### Already Supported (TSDB)
NRL (`nrl`), Super Rugby Pacific (`super-rugby`)

### ESPN Coverage — Excellent

ESPN has rugby under **two sports**: `rugby` (union) and `rugby-league`.

Rugby union uses **numeric slug IDs** (e.g., `180659` for Six Nations), not string slugs.

| League | ESPN Slug | ID | Teams | Tier | Notes |
|--------|-----------|-----|-------|------|-------|
| Six Nations | `rugby/180659` | 8323 | 6 | 1 | **Active — games today!** |
| Rugby Championship | `rugby/244293` | 8328 | 4 | 1 | Aug-Sep season |
| Rugby World Cup | `rugby/164205` | 8337 | 20 | 1 | Quadrennial |
| Premiership Rugby | `rugby/267979` | 8007 | 10 | 1 | Active season |
| French Top 14 | `rugby/270559` | 8005 | 14 | 1 | **Active — games today!** |
| United Rugby Championship | `rugby/270557` | 8331 | 16 | 1 | Active season |
| Euro Champions Cup | `rugby/271937` | 8329 | 24 | 1 | Active season |
| Super Rugby Pacific | `rugby/242041` | 8326 | 12 | 1 | **Active — games today!** |
| Major League Rugby | `rugby/289262` | 19114 | 12 | 1 | Starting Mar 2026 |
| NRL | `rugby-league/3` | 8370 | 17 | 1 | Starting Mar 2026 |
| Intl Test Match | `rugby/289234` | 10659 | ? | 1 | Windows (Jun, Nov) |
| Women's Rugby WC | `rugby/289237` | 17953 | ? | 1 | Quadrennial |
| Olympic Men's 7s | `rugby/282` | 10743 | 12 | 1 | Summer Olympics |
| Olympic Women's 7s | `rugby/283` | 10729 | 12 | 1 | Summer Olympics |

### Provider Consideration: NRL + Super Rugby Upgrade

NRL and Super Rugby are currently on TSDB. ESPN has them with better data. Could **upgrade to ESPN** (Tier 1) and drop the TSDB dependency for these two.

### TSDB Rugby (premium, additional leagues)

| League | TSDB ID | Tier | Notes |
|--------|---------|------|-------|
| Six Nations | 4714 | (prefer ESPN) | 12 events, active |
| English Super League (Rugby League) | 4415 | 2 | 20 events |
| Japan Rugby League One | 5167 | 2 | 20 events |
| French Pro D2 | 5172 | 2 | Niche |

**Implementation:** Core rugby union leagues are all Tier 1 via ESPN. NRL/Super Rugby can be upgraded from TSDB to ESPN. Niche leagues (Super League, Japan) are Tier 2.

**ESPN provider note:** Rugby uses numeric slug IDs (`180659`) instead of string slugs. The ESPN provider may need a small tweak to handle `rugby/180659` format in the `provider_league_id` field. Verify the scoreboard endpoint format works: `sports/rugby/180659/scoreboard`.

---

## Implementation Roadmap

### Phase 1: Quick Wins (Tier 1, ESPN, no refactor needed)

**Soccer — WCQ + Nations League:**
- 8 new leagues, all ESPN, same provider pattern
- Most impactful: UEFA WCQ (12 events in Mar), Friendlies (59 events)
- Estimated: schema additions only

**Basketball — FIBA + NBL + Olympics:**
- 4 new leagues (fiba, nbl, mens/womens-olympics-basketball)
- NBL is actively in-season

**Rugby Union (requires ESPN provider slug format validation):**
- 9+ new ESPN leagues
- Upgrade NRL + Super Rugby from TSDB → ESPN
- Six Nations and Top 14 are live RIGHT NOW
- Need to verify numeric slug IDs work in ESPN provider

**Olympics — Summer sports:**
- Soccer, basketball, rugby 7s, golf, baseball
- All ESPN, seasonal/quadrennial

### Phase 2: Tiered Model (`teamarrv2-s9n`)

- BYOK TSDB key support in Settings
- Tier flag on leagues (schema or derived)
- Frontend gating for Tier 2 leagues

### Phase 3: Tier 2 Leagues (after s9n)

- Handball (6+ TSDB leagues)
- Rugby niche (Super League, Japan League One)
- European club basketball (if TSDB covers it)
- Any other TSDB-only leagues

### Dependencies

```
Phase 1 (ESPN leagues)  →  no blockers, can start now
Phase 2 (s9n refactor)  →  design decision on tier storage
Phase 3 (TSDB leagues)  →  blocked by Phase 2
```

### Open Questions

1. **Rugby slug format** — ESPN uses numeric IDs for rugby (`180659`). Does our ESPN provider handle `sports/rugby/180659/scoreboard`? Need to verify.
2. **Soccer slug format** — ESPN international soccer uses dots (`fifa.worldq.uefa`). Does our ESPN provider handle dots in league IDs?
3. **Curling** — No ESPN, no known API. Likely out of scope unless someone finds a source.
4. **European club basketball** — Check if TSDB has EuroLeague/EuroCup with premium key.
