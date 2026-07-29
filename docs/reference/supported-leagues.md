---
title: Supported Leagues
parent: Technical Reference
nav_order: 1
---

# Supported Sports & Leagues

Teamarr supports **170 pre-configured leagues** across 15 sports, plus **~250 dynamically discovered soccer leagues** from ESPN. Pre-configured leagues have full support (team import + event matching). Discovered leagues support event matching only.

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
| **NASCAR** | NASCAR Cup, O'Reilly (Xfinity), and Truck series via the official cf.nascar.com schedule API. Full race-weekend sessions, no API key required. See [provider docs](providers/nascar). |
| **MLB Stats API** | Minor League Baseball (MiLB) — Triple-A, Double-A, High-A, Single-A, Rookie |
| **Squiggle** | AFL (Australian Football League). Free, no API key required. See [provider docs](providers/squiggle). |
| **HockeyTech** | Canadian and US junior/minor hockey leagues (CHL, AHL, ECHL, PWHL, USHL, Junior A) |
| **Supabase** | Supabase-backed leagues such as the Canadian Baseball League (CBL). No API key required. See [provider docs](providers/supabase). |
| **TheSportsDB** | Rugby, cricket, boxing, CFL, Scandinavian leagues, and more. Free and [premium tiers](providers/tsdb.md). |

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
| National Basketball League (Australia) | `nbl` | ESPN |
| FIBA Basketball World Cup | `fiba` | TSDB (premium) |
| FIBA Women's Basketball World Cup | `fibaw` | TSDB (premium) |
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
| Swedish Hockey League | `shl` | TSDB **P** |

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
| Uruguayan Segunda División (AUF Segunda) | `uru.2` | TSDB **P** |

#### Brazilian state championships

All 27 Brazilian state championships (*campeonatos estaduais*) are supported. ESPN covers four (free, with richer match data); the remaining 23 come from TheSportsDB and require a premium key (**P**). State championships run roughly January–April.

| League | ID | Provider |
|--------|-----|----------|
| Campeonato Carioca (Rio de Janeiro) | `carioca` | ESPN |
| Campeonato Paulista (São Paulo) | `paulista` | ESPN |
| Campeonato Gaúcho (Rio Grande do Sul) | `gaucho` | ESPN |
| Campeonato Mineiro (Minas Gerais) | `mineiro` | ESPN |
| Campeonato Acreano (Acre) | `acreano` | TSDB **P** |
| Campeonato Alagoano (Alagoas) | `alagoano` | TSDB **P** |
| Campeonato Amapaense (Amapá) | `amapaense` | TSDB **P** |
| Campeonato Amazonense (Amazonas) | `amazonense` | TSDB **P** |
| Campeonato Baiano (Bahia) | `baiano` | TSDB **P** |
| Campeonato Brasiliense (Distrito Federal) | `brasiliense` | TSDB **P** |
| Campeonato Capixaba (Espírito Santo) | `capixaba` | TSDB **P** |
| Campeonato Catarinense (Santa Catarina) | `catarinense` | TSDB **P** |
| Campeonato Cearense (Ceará) | `cearense` | TSDB **P** |
| Campeonato Goiano (Goiás) | `goiano` | TSDB **P** |
| Campeonato Maranhense (Maranhão) | `maranhense` | TSDB **P** |
| Campeonato Mato-Grossense (Mato Grosso) | `matogrossense` | TSDB **P** |
| Campeonato Paraense (Pará) | `paraense` | TSDB **P** |
| Campeonato Paraibano (Paraíba) | `paraibano` | TSDB **P** |
| Campeonato Paranaense (Paraná) | `paranaense` | TSDB **P** |
| Campeonato Pernambucano (Pernambuco) | `pernambucano` | TSDB **P** |
| Campeonato Piauiense (Piauí) | `piauiense` | TSDB **P** |
| Campeonato Potiguar (Rio Grande do Norte) | `potiguar` | TSDB **P** |
| Campeonato Rondoniense (Rondônia) | `rondoniense` | TSDB **P** |
| Campeonato Roraimense (Roraima) | `roraimense` | TSDB **P** |
| Campeonato Sergipano (Sergipe) | `sergipano` | TSDB **P** |
| Campeonato Sul-Mato-Grossense (Mato Grosso do Sul) | `sulmatogrossense` | TSDB **P** |
| Campeonato Tocantinense (Tocantins) | `tocantinense` | TSDB **P** |

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
| NASCAR Cup Series | `nascar-cup` | NASCAR API | Event |
| NASCAR O'Reilly Auto Parts Series | `nascar-xfinity` | NASCAR API | Event |
| NASCAR Craftsman Truck Series | `nascar-truck` | NASCAR API | Event |
| IndyCar Series | `indycar` | ESPN | Event |
| IMSA SportsCar Championship | `imsa` | TSDB **P** | Event |
| FIA World Endurance Championship | `wec` | TSDB **P** | Event |

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
| Indian Premier League | `ipl` | TSDB **P** |
| Big Bash League | `bbl` | TSDB **P** |
| SA20 | `sa20` | TSDB **P** |
| Major League Cricket | `mlc` | TSDB |

{: .note }
IPL, BBL, and SA20 are TSDB premium tier — a [premium API key](providers/tsdb.md) is required for full event coverage of their long seasons. Major League Cricket works on the free tier: its short T20 season fits within TSDB's free rolling next-events window.

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
