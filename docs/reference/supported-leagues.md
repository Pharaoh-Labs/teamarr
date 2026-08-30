---
title: Supported Leagues
parent: Technical Reference
nav_order: 1
---

# Supported Sports & Leagues

Teamarr supports **174 pre-configured leagues** across 15 sports, plus **~228 dynamically discovered soccer leagues** from ESPN. Most pre-configured leagues have full support (team import + event matching) — see the Support Levels table below for the event-only exceptions. Discovered leagues support event matching only.

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
| **ESPN** | Primary provider for most US leagues and international soccer. Discovers ~228 soccer leagues dynamically. |
| **Bell Media** | Canadian Football League via TSN's public sports widget API. |
| **NASCAR** | NASCAR Cup, O'Reilly (Xfinity), and Truck series via the official cf.nascar.com schedule API. Full race-weekend sessions, no API key required. See [provider docs](providers/nascar). |
| **MLB Stats API** | Minor League Baseball (MiLB) — Triple-A, Double-A, High-A, Single-A, Rookie |
| **Squiggle** | AFL (Australian Football League). Free, no API key required. See [provider docs](providers/squiggle). |
| **HockeyTech** | Canadian and US junior/minor hockey leagues (CHL, AHL, ECHL, PWHL, USHL, Junior A) |
| **Supabase** | Supabase-backed leagues such as the Canadian Baseball League (CBL). No API key required. See [provider docs](providers/supabase). |
| **TheSportsDB** | Rugby, cricket, boxing, Scandinavian leagues, and more. Requires a [premium API key](providers/tsdb.md). |

### TSDB Key Requirement

Every TSDB-sourced league requires a [TheSportsDB premium API key](providers/tsdb.md). Without one, TSDB leagues are unavailable — no events, no team channels — and the league picker marks them with a crown.

| Tier | Meaning |
|------|---------|
| TSDB | Requires a TheSportsDB premium key |

---

## Football

NCAA Football aggregates ESPN's FBS, FCS, lower-division, and cross-division fixtures.

| League | ID | Provider |
|--------|-----|----------|
| National Football League | `nfl` | ESPN |
| Canadian Football League | `cfl` | Bell Media |
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
| National Basketball League (Australia) | `nbl` | ESPN |
| FIBA Basketball World Cup | `fiba` | TSDB |
| FIBA Women's Basketball World Cup | `fibaw` | TSDB |
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
| Greater Ontario Hockey League | `gohl` | HockeyTech |

### European

| League | ID | Provider |
|--------|-----|----------|
| Norwegian Fjordkraft-ligaen | `norwegian-hockey` | TSDB |
| Swedish Hockey League | `shl` | TSDB |

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
| Canadian Baseball League | `cbl` | Supabase |
| WPBL (Women's Pro Baseball) | `wpbl` | TSDB |
| World Baseball Classic | `wbc` | ESPN |
| Little League Baseball | `llb` | ESPN |
| NCAA Baseball | `ncaabb` | ESPN |
| NCAA Softball | `ncaasbw` | ESPN |

---

## Soccer

{: .tip }
Teamarr automatically discovers **~228 soccer leagues** from ESPN's API during cache refresh. The leagues listed below are the pre-configured ones with full support (team import + event matching). All discovered leagues are available for event matching in event groups — select them from the league picker under the Soccer sport.

### North America

| League | ID | Provider |
|--------|-----|----------|
| Major League Soccer | `mls` | ESPN |
| National Women's Soccer League | `nwsl` | ESPN |
| NCAA Men's Soccer | `ncaas` | ESPN |
| NCAA Women's Soccer | `ncaaws` | ESPN |
| Liga MX | `ligamx` | ESPN |
| Canadian Premier League | `can.1` | TSDB |

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
| Northern Irish Premiership | `nifl.1` | TSDB |

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
| Venezuelan Segunda División | `ven.2` | TSDB |
| Uruguayan Segunda División (AUF Segunda) | `uru.2` | TSDB |

#### Brazilian state championships

All 27 Brazilian state championships (*campeonatos estaduais*) are supported. ESPN covers four (no key needed, with richer match data); the remaining 23 come from TheSportsDB and require a premium key. State championships run roughly January–April.

| League | ID | Provider |
|--------|-----|----------|
| Campeonato Carioca (Rio de Janeiro) | `carioca` | ESPN |
| Campeonato Paulista (São Paulo) | `paulista` | ESPN |
| Campeonato Gaúcho (Rio Grande do Sul) | `gaucho` | ESPN |
| Campeonato Mineiro (Minas Gerais) | `mineiro` | ESPN |
| Campeonato Acreano (Acre) | `acreano` | TSDB |
| Campeonato Alagoano (Alagoas) | `alagoano` | TSDB |
| Campeonato Amapaense (Amapá) | `amapaense` | TSDB |
| Campeonato Amazonense (Amazonas) | `amazonense` | TSDB |
| Campeonato Baiano (Bahia) | `baiano` | TSDB |
| Campeonato Brasiliense (Distrito Federal) | `brasiliense` | TSDB |
| Campeonato Capixaba (Espírito Santo) | `capixaba` | TSDB |
| Campeonato Catarinense (Santa Catarina) | `catarinense` | TSDB |
| Campeonato Cearense (Ceará) | `cearense` | TSDB |
| Campeonato Goiano (Goiás) | `goiano` | TSDB |
| Campeonato Maranhense (Maranhão) | `maranhense` | TSDB |
| Campeonato Mato-Grossense (Mato Grosso) | `matogrossense` | TSDB |
| Campeonato Paraense (Pará) | `paraense` | TSDB |
| Campeonato Paraibano (Paraíba) | `paraibano` | TSDB |
| Campeonato Paranaense (Paraná) | `paranaense` | TSDB |
| Campeonato Pernambucano (Pernambuco) | `pernambucano` | TSDB |
| Campeonato Piauiense (Piauí) | `piauiense` | TSDB |
| Campeonato Potiguar (Rio Grande do Norte) | `potiguar` | TSDB |
| Campeonato Rondoniense (Rondônia) | `rondoniense` | TSDB |
| Campeonato Roraimense (Roraima) | `roraimense` | TSDB |
| Campeonato Sergipano (Sergipe) | `sergipano` | TSDB |
| Campeonato Sul-Mato-Grossense (Mato Grosso do Sul) | `sulmatogrossense` | TSDB |
| Campeonato Tocantinense (Tocantins) | `tocantinense` | TSDB |

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
| Svenska Cupen (Sweden) | `svenska-cupen` | TSDB |
| Swedish Superettan | `swe.2` | TSDB |
| Swedish Division 1 North | `swe.3.n` | TSDB |
| Swedish Division 1 South | `swe.3.s` | TSDB |
| Icelandic Úrvalsdeild karla | `ice.1` | TSDB |
| Icelandic 1. deild karla | `ice.2` | TSDB |

### Other Regions

| League | ID | Provider |
|--------|-----|----------|
| Gambia GFA League | `gam.1` | TSDB |
| Aruban Division di Honor | `arb.1` | TSDB |

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
| NASCAR Cup Series | `nascar-cup` | NASCAR API | Event |
| NASCAR O'Reilly Auto Parts Series | `nascar-xfinity` | NASCAR API | Event |
| NASCAR Craftsman Truck Series | `nascar-truck` | NASCAR API | Event |
| IndyCar Series | `indycar` | ESPN | Event |
| IMSA WeatherTech SportsCar Championship | `imsa` | TSDB | Event |
| FIA World Endurance Championship | `wec` | TSDB | Event |

Motorsports events are race weekends made up of multiple sessions (Practice,
Qualifying, Race), each exposed as its own EPG program block. See the
[TSDB provider docs](providers/tsdb.md) for the IMSA/WEC session grouping.
MotoGP (`motogp`) is currently disabled (`leagues.enabled = 0`) because ESPN's
`racing/motogp` endpoint returns no usable schedule or logo data.

---

## Tennis

{: .warning }
Tennis is **Event Only** - no team import available (players, not teams).

| League | ID | Provider | Type |
|--------|-----|----------|------|
| ATP Tour | `atp` | ESPN | Event |
| WTA Tour | `wta` | ESPN | Event |

Tennis is matched **per match** — one channel per match, with the two players
filling the home/away variables plus tennis-specific variables
(`{player1}`, `{player2}`, `{tournament_name}`, `{tennis_round}`, …).
Court and round day-feeds fan out to every match on that court/round for the
day. See the [ESPN provider docs](providers/espn) for grand-slam draw
splitting and matching details.

---

## Cricket

| League | ID | Provider |
|--------|-----|----------|
| Indian Premier League | `ipl` | TSDB |
| Big Bash League | `bbl` | TSDB |
| SA20 | `sa20` | TSDB |
| Major League Cricket | `mlc` | TSDB |

{: .note }
All four are TSDB-sourced, so a [premium API key](providers/tsdb.md) is required.

---

## Rugby

| League | ID | Provider |
|--------|-----|----------|
| Rugby World Cup | `rwc` | ESPN |
| Women's Rugby World Cup | `wrwc` | ESPN |
| Six Nations | `6n` | ESPN |
| The Rugby Championship | `trc` | ESPN |
| Nations Championship | `natchamp` | ESPN |
| Super Rugby Pacific | `srp` | ESPN |
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
| English Rugby League Super League | `super-league` | TSDB |

---

## Australian Football

| League | ID | Provider |
|--------|-----|----------|
| Australian Football League | `afl` | [Squiggle](providers/squiggle) |

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
