---
title: Supported Leagues
parent: Technical Reference
nav_order: 1
docs_version: "2.3.1"
---

# Supported Sports & Leagues

Teamarr supports **132 pre-configured leagues** across 14 sports, plus **~250 dynamically discovered soccer leagues** from ESPN. Pre-configured leagues have full support (team import + event matching). Discovered leagues support event matching only.

## Support Levels

Leagues have different levels of support:

| Level | Team Import | Event Matching | Description |
|-------|-------------|----------------|-------------|
| **Full** | Yes | Yes | Teams can be added for team-based channels; streams matched to events |
| **Event Only** | No | Yes | Event groups can match streams to events; no team import |

{: .note }
**Team Import** = Add teams to Teams page for dedicated team channels
**Event Matching** = Event groups can match M3U streams to sporting events

## Data Providers

| Provider | Description |
|----------|-------------|
| **ESPN** | Primary provider for most US leagues and international soccer. Discovers ~250 soccer leagues dynamically. |
| **MLB Stats API** | Minor League Baseball (MiLB) — Triple-A, Double-A, High-A, Single-A, Rookie |
| **Squiggle** | AFL (Australian Football League). Free, no API key required. See [provider docs](providers/squiggle.md). |
| **TheSportsDB** | Rugby, cricket, boxing, CFL, Scandinavian leagues, and more. Free and [premium tiers](providers/tsdb.md). |
| **HockeyTech** | Canadian and US junior/minor hockey leagues (CHL, AHL, ECHL, PWHL, USHL, Junior A) |

### TSDB Tier Legend

TSDB leagues are classified by tier. Most work on the free tier. Leagues marked with a crown (**P**) require a [premium API key](providers/tsdb.md) for full event coverage.

| Tier | Meaning |
|------|---------|
| TSDB | Works on free tier (low event volume) |
| TSDB **P** | Requires premium key for full coverage |

---

## Football

| League | ID | Provider |
|--------|-----|----------|
| National Football League | `nfl` | ESPN |
| Canadian Football League | `cfl` | TSDB |
| NCAA Football | `ncaaf` | ESPN |
| United Football League | `ufl` | ESPN |

---

## Basketball

| League | ID | Provider |
|--------|-----|----------|
| National Basketball Association | `nba` | ESPN |
| NBA G League | `nbag` | ESPN |
| Women's National Basketball Association | `wnba` | ESPN |
| NCAA Men's Basketball | `ncaam` | ESPN |
| NCAA Women's Basketball | `ncaaw` | ESPN |
| Unrivaled | `unrivaled` | TSDB |

---

## Hockey

### NHL, NCAA & Olympics

| League | ID | Provider |
|--------|-----|----------|
| National Hockey League | `nhl` | ESPN |
| NCAA Men's Ice Hockey | `ncaah` | ESPN |
| NCAA Women's Ice Hockey | `ncaawh` | ESPN |
| Men's Ice Hockey - Olympics | `olymh` | ESPN |
| Women's Ice Hockey - Olympics | `olywh` | ESPN |

### Canadian Major Junior (CHL)

| League | ID | Provider |
|--------|-----|----------|
| Canadian Hockey League | `chl` | HockeyTech |
| Ontario Hockey League | `ohl` | HockeyTech |
| Western Hockey League | `whl` | HockeyTech |
| Quebec Major Junior Hockey League | `qmjhl` | HockeyTech |

### Pro/Minor Pro

| League | ID | Provider |
|--------|-----|----------|
| American Hockey League | `ahl` | HockeyTech |
| East Coast Hockey League | `echl` | HockeyTech |
| Professional Women's Hockey League | `pwhl` | HockeyTech |

### US Junior

| League | ID | Provider |
|--------|-----|----------|
| United States Hockey League | `ushl` | HockeyTech |

### Canadian Junior A

| League | ID | Provider |
|--------|-----|----------|
| Ontario Junior Hockey League | `ojhl` | HockeyTech |
| British Columbia Hockey League | `bchl` | HockeyTech |
| Saskatchewan Junior Hockey League | `sjhl` | HockeyTech |
| Alberta Junior Hockey League | `ajhl` | HockeyTech |
| Manitoba Junior Hockey League | `mjhl` | HockeyTech |
| Maritime Junior Hockey League | `mhl` | HockeyTech |

### European

| League | ID | Provider |
|--------|-----|----------|
| Norwegian Fjordkraft-ligaen | `norwegian-hockey` | TSDB |

---

## Baseball & Softball

| League | ID | Provider |
|--------|-----|----------|
| Major League Baseball | `mlb` | ESPN |
| Triple-A (MiLB) | `milb-aaa` | MLB Stats |
| Double-A (MiLB) | `milb-aa` | MLB Stats |
| High-A (MiLB) | `milb-high-a` | MLB Stats |
| Single-A (MiLB) | `milb-a` | MLB Stats |
| Rookie (MiLB) | `rookie` | MLB Stats |
| World Baseball Classic | `wbc` | ESPN |
| NCAA Baseball | `ncaabb` | ESPN |
| NCAA Softball | `ncaasbw` | ESPN |

---

## Soccer

{: .tip }
Teamarr automatically discovers **~250 soccer leagues** from ESPN's API during cache refresh. The leagues listed below are the pre-configured ones with full support (team import + event matching). All discovered leagues are available for event matching in event groups — select them from the league picker under the Soccer sport.

### North America

| League | ID | Provider |
|--------|-----|----------|
| Major League Soccer | `mls` | ESPN |
| National Women's Soccer League | `nwsl` | ESPN |
| NCAA Men's Soccer | `ncaas` | ESPN |
| NCAA Women's Soccer | `ncaaws` | ESPN |
| Liga MX | `ligamx` | ESPN |
| Canadian Premier League | `can.1` | TSDB **P** |

### England

| League | ID | Provider |
|--------|-----|----------|
| English Premier League | `epl` | ESPN |
| EFL Championship | `championship` | ESPN |
| EFL League One | `league-one` | ESPN |
| EFL League Two | `league-two` | ESPN |
| FA Cup | `fa-cup` | ESPN |
| EFL Cup (Carabao Cup) | `league-cup` | ESPN |

### Europe - Top Leagues

| League | ID | Provider |
|--------|-----|----------|
| La Liga (Spain) | `laliga` | ESPN |
| Copa del Rey | `copa-del-rey` | ESPN |
| Bundesliga (Germany) | `bundesliga` | ESPN |
| 2. Bundesliga (Germany) | `2-bundesliga` | ESPN |
| DFB-Pokal | `dfb-pokal` | ESPN |
| Serie A (Italy) | `seriea` | ESPN |
| Coppa Italia | `coppa-italia` | ESPN |
| Ligue 1 (France) | `ligue1` | ESPN |
| Coupe de France | `coupe-de-france` | ESPN |
| Eredivisie (Netherlands) | `eredivisie` | ESPN |
| Primeira Liga (Portugal) | `primeira` | ESPN |
| Belgian Pro League | `jupiler` | ESPN |
| Scottish Premiership | `spfl` | ESPN |
| Swiss Super League | `swiss-super-league` | ESPN |
| Turkish Süper Lig | `super-lig` | ESPN |
| Greek Super League | `greek-super-league` | ESPN |
| Saudi Pro League | `spl` | ESPN |
| Northern Irish Premiership | `nifl.1` | TSDB **P** |

### UEFA Competitions

| League | ID | Provider |
|--------|-----|----------|
| UEFA Champions League | `ucl` | ESPN |
| UEFA Europa League | `uel` | ESPN |
| UEFA Europa Conference League | `uecl` | ESPN |

### South America

| League | ID | Provider |
|--------|-----|----------|
| Argentine Liga Profesional | `lpa` | ESPN |
| Brazilian Serie A | `brasileirao` | ESPN |
| Colombian Primera A | `dimayor` | ESPN |
| Copa Libertadores | `libertadores` | ESPN |
| Copa Sudamericana | `sudamericana` | ESPN |
| Venezuelan Segunda División | `ven.2` | TSDB **P** |

### International

| League | ID | Provider |
|--------|-----|----------|
| FIFA World Cup | `world-cup` | ESPN |
| FIFA Women's World Cup | `wwc` | ESPN |
| UEFA European Championship | `euro` | ESPN |
| Copa America | `copa-america` | ESPN |
| CONCACAF Gold Cup | `gold-cup` | ESPN |
| CONCACAF Nations League | `cnl` | ESPN |

### Scandinavia

| League | ID | Provider |
|--------|-----|----------|
| Svenska Cupen (Sweden) | `svenska-cupen` | TSDB **P** |
| Swedish Superettan | `swe.2` | TSDB **P** |
| Swedish Division 1 North | `swe.3.n` | TSDB **P** |
| Swedish Division 1 South | `swe.3.s` | TSDB **P** |
| Icelandic Úrvalsdeild karla | `ice.1` | TSDB **P** |
| Icelandic 1. deild karla | `ice.2` | TSDB **P** |
| Uruguayan Segunda División | `uru.2` | TSDB **P** |

### Other Regions

| League | ID | Provider |
|--------|-----|----------|
| Gambia GFA League | `gam.1` | TSDB **P** |
| Aruban Division di Honor | `arb.1` | TSDB **P** |

### Asia/Pacific

| League | ID | Provider |
|--------|-----|----------|
| J1 League (Japan) | `jleague` | ESPN |
| A-League Men (Australia) | `aleague` | ESPN |

---

## Combat Sports

{: .warning }
Combat sports are **Event Only** - no team import available.

| League | ID | Provider | Type |
|--------|-----|----------|------|
| Ultimate Fighting Championship | `ufc` | ESPN | Event Card |
| Boxing | `boxing` | TSDB | Event Card |

Combat sports use "Event Card" matching rather than team vs team matching.

---

## Motorsports

{: .warning }
Motorsports are **Event Only** - no team import available.

| League | ID | Provider | Type |
|--------|-----|----------|------|
| Formula 1 | `f1` | ESPN | Event |
| NASCAR Cup Series | `nascar-cup` | ESPN | Event |
| NASCAR Xfinity Series | `nascar-xfinity` | ESPN | Event |
| NASCAR Craftsman Truck Series | `nascar-truck` | ESPN | Event |
| IndyCar Series | `indycar` | ESPN | Event |
| IMSA SportsCar Championship | `imsa` | TSDB | Event |
| FIA World Endurance Championship | `wec` | TSDB **P** | Event |

Motorsports events are race weekends made up of multiple sessions (Practice,
Qualifying, Race). Each session is exposed as its own EPG program block. `f1`
is the fully verified ESPN reference league; the other ESPN-backed series are
configured against their ESPN scoreboard endpoints but session coverage may
vary by series. `imsa` and `wec` are backed by TSDB, which groups its flat
per-session events into the same multi-session shape — see the
[TSDB provider docs](providers/tsdb.md) for details and the free-tier caveat
for WEC.

MotoGP (`motogp`) is currently disabled (`leagues.enabled = 0`) because ESPN's
`racing/motogp` scoreboard endpoint returns no usable schedule or logo data.
A TSDB-backed migration (idLeague 4407), similar to the IMSA/WEC session
grouping above, is planned as a future enhancement.

---

## Cricket

| League | ID | Provider |
|--------|-----|----------|
| Indian Premier League | `ipl` | TSDB **P** |
| Big Bash League | `bbl` | TSDB **P** |
| SA20 | `sa20` | TSDB **P** |

{: .note }
Cricket leagues are TSDB premium tier. A [premium API key](providers/tsdb.md) is required for full event coverage.

---

## Rugby

| League | ID | Provider |
|--------|-----|----------|
| Rugby World Cup | `rwc` | ESPN |
| Women's Rugby World Cup | `wrwc` | ESPN |
| Six Nations | `6n` | ESPN |
| The Rugby Championship | `trc` | ESPN |
| Super Rugby Pacific | `super-rugby` | ESPN |
| United Rugby Championship | `urc` | ESPN |
| Gallagher Premiership | `prem` | ESPN |
| French Top 14 | `top14` | ESPN |
| European Rugby Champions Cup | `ercc` | ESPN |
| European Rugby Challenge Cup | `epcr` | ESPN |
| Major League Rugby | `mlr` | ESPN |
| Currie Cup | `cc` | ESPN |
| National Provincial Championship | `npc` | ESPN |
| URBA Primera A | `urba` | ESPN |
| International Test Match | `itm` | ESPN |
| British and Irish Lions Tour | `lions` | ESPN |
| Olympic Men's Rugby Sevens | `om7s` | ESPN |
| Olympic Women's Rugby Sevens | `ow7s` | ESPN |
| National Rugby League (Australia) | `nrl` | ESPN |

---

## Australian Football

| League | ID | Provider |
|--------|-----|----------|
| Australian Football League | `afl` | [Squiggle](providers/squiggle.md) |

{: .note }
AFL is served by the Squiggle provider — free, no API key required. Includes team records, ladder ranking, and team logos.

---

## Lacrosse

| League | ID | Provider |
|--------|-----|----------|
| National Lacrosse League | `nll` | ESPN |
| Premier Lacrosse League | `pll` | ESPN |
| NCAA Men's Lacrosse | `ncaalax` | ESPN |
| NCAA Women's Lacrosse | `ncaawlax` | ESPN |

---

## Volleyball

| League | ID | Provider |
|--------|-----|----------|
| NCAA Men's Volleyball | `ncaavb` | ESPN |
| NCAA Women's Volleyball | `ncaawvb` | ESPN |

---

## Adding New Leagues

New leagues are added to the `INSERT OR REPLACE INTO leagues` block in `teamarr/database/schema.sql`. Each league requires a provider, league ID, display name, sport, and optionally logos and TSDB tier. See the [Providers](providers/) section for details on each provider's ID format.

If you need a league that isn't listed here, please open an issue on [GitHub](https://github.com/Pharaoh-Labs/teamarr/issues).
