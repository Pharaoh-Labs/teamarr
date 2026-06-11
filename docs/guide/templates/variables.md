---
title: Variables
parent: Templates
grand_parent: User Guide
nav_order: 2
docs_version: "2.3.0"
---

# Template Variables

Templates use variables enclosed in curly braces that get replaced with real data when EPG is generated. Teamarr provides 207 variables across 17 categories.

## Team vs Event Templates

Variables are scoped to the template type they make sense in. The template editor's variable picker only surfaces variables that apply to the template you're editing.

- **Team templates** have an "our team" perspective — the subscribed team is the anchor. These templates expose team-perspective variables like `{team}`, `{opponent}`, `{is_home}`, `{team_record}`, `{win_streak}`, `{result}`, `{odds_moneyline}`, and similar "my team vs the other team" variables.
- **Event templates** are positional — they describe a matchup without a reference team. These templates expose positional variables like `{home_team}`, `{away_team}`, `{home_team_record}`, and game-level data. Event templates additionally expose the feed-team family (`{feed_team}`, `{feed_team_short}`, `{is_home_feed}`, etc.) for feed-separated channels.
- **Shared variables** (most of the list) are available in both — positional teams, venue, date/time, playoffs, odds (excluding the team-perspective `{odds_moneyline}` pair), soccer, combat sports, and league/sport identifiers.

If you hand-type a scope-restricted variable into a template where it doesn't belong (e.g., `{team}` in an event template), it will still resolve (backward compatibility), but the picker won't offer it. Use the picker to stay within the intended scope.

## Suffix Support

**Team templates** support suffixes to reference different games:

| Suffix | Context | Example |
|--------|---------|---------|
| (none) | Current game | `{opponent}` |
| `.next` | Next upcoming game | `{opponent.next}` |
| `.last` | Most recent game | `{opponent.last}` |

**Event templates** don't need suffixes - each channel exists for a single game, so there's no "next" or "last" to reference.

In the tables below, the **Suffixes** column indicates which suffixes are available:
- **base** = no suffix (current game)
- **.next** = next game
- **.last** = last game

---

## Artwork & Game Thumbs

Three template fields hold image URLs and accept the same variables as any other field:

| Field | Used for |
|-------|----------|
| **Program Art URL** (`program_art_url`) | the programme `<icon>` in the EPG (per-game artwork) |
| **Channel Logo URL** (`event_channel_logo_url`, event templates) | the Dispatcharr channel logo **and** the EPG channel icon |
| **Filler Art URL** (pregame/postgame/idle `art_url`) | artwork on filler programmes |

### Game-Thumbs base URL

Instead of writing the full image host in every template, set it **once** in
**EPG → Output → Game Thumbs → Game-Thumbs Base URL** (e.g. your
[Game Thumbs](../game-thumbs) host). Templates then store only the **relative path**,
always starting with `/`:

```
/{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png?style=6&logo=true&fallback=true
```

At generation the base URL — host **and port**, exactly as you entered it — is prefixed onto the
relative path. Rules:

- **Relative paths** (start with `/`) get the base prefixed.
- **Absolute URLs** (anything with `http://`/`https://`) are left **unchanged**, so you can
  still hardcode a one-off full URL in a single field.
- Empty base URL = no prefixing (every art field must then be a full URL).

The same reconstructed URL is sent everywhere it's needed — the EPG `<icon>` **and** the
Dispatcharr channel logo — so the guide artwork and the channel logo always match. The
live preview in the template editor applies the base URL too, so what you see matches the
generated output (and renders the actual image so you can confirm the link resolves).

---

## Identity

Core identifiers for teams, leagues, and matchups.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{team_name}` | Team display name | base | `Detroit Lions` |
| `{team_abbrev}` | Team abbreviation uppercase | base | `DET` |
| `{team_abbrev_lower}` | Team abbreviation lowercase | base | `det` |
| `{team_name_pascal}` | Team name in PascalCase for channel IDs | base | `DetroitLions` |
| `{team_short}` | Team short name | base | `Lions` |
| `{opponent}` | Opponent team name | base, .next, .last | `Chicago Bears` |
| `{opponent_abbrev}` | Opponent team abbreviation uppercase | base, .next, .last | `CHI` |
| `{opponent_abbrev_lower}` | Opponent abbreviation lowercase | base, .next, .last | `chi` |
| `{opponent_short}` | Opponent short name | base, .next, .last | `Bears` |
| `{matchup}` | Full matchup string | base, .next, .last | `Chicago Bears @ Detroit Lions` |
| `{matchup_abbrev}` | Abbreviated matchup uppercase | base, .next, .last | `CHI @ DET` |
| `{matchup_short}` | Short name matchup | base, .next, .last | `Bears @ Lions` |
| `{league}` | League short alias | base | `NFL` |
| `{league_name}` | League full display name | base | `National Football League` |
| `{league_id}` | League identifier for URLs | base | `nfl` |
| `{league_code}` | Raw league code | base | `nfl` |
| `{sport}` | Sport display name | base | `Football` |
| `{sport_lower}` | Sport in lowercase | base | `football` |
| `{gracenote_category}` | Gracenote category for EPG | base | `NFL Football` |
| `{exception_keyword}` | Exception keyword label (e.g., 'Spanish', '4K') | base | `4K` |

---

## Date & Time

Game scheduling information.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{game_date}` | Full game date | base, .next, .last | `Sunday, December 22, 2024` |
| `{game_date_short}` | Short game date | base, .next, .last | `Dec 22` |
| `{game_day}` | Day of week | base, .next, .last | `Sunday` |
| `{game_day_short}` | Short day of week | base, .next, .last | `Sun` |
| `{game_time}` | Game time formatted per user settings | base, .next, .last | `1:00 PM EST` |
| `{days_until}` | Days until game | base, .next, .last | `0` |
| `{today_tonight}` | 'today' or 'tonight' based on 5pm cutoff | base, .next, .last | `today` |
| `{today_tonight_title}` | 'Today' or 'Tonight' (title case) | base, .next, .last | `Today` |
| `{relative_day}` | Relative day: 'today', 'tonight', 'tomorrow', day of week, or date | base, .next | `tomorrow` |
| `{relative_day_title}` | Relative day (title case) | base, .next | `Tomorrow` |

---

## Venue

Stadium and location information.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{venue}` | Stadium/arena name | base, .next, .last | `Ford Field` |
| `{venue_city}` | Venue city | base, .next, .last | `Detroit` |
| `{venue_state}` | Venue state | base, .next, .last | `MI` |
| `{venue_full}` | Full venue location | base, .next, .last | `Ford Field, Detroit, MI` |

---

## Home/Away

Positional team references and home/away context.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{home_team}` | Home team name (positional) | base, .next, .last | `Detroit Lions` |
| `{home_team_abbrev}` | Home team abbreviation uppercase | base, .next, .last | `DET` |
| `{home_team_abbrev_lower}` | Home team abbreviation lowercase | base, .next, .last | `det` |
| `{home_team_pascal}` | Home team name in PascalCase | base, .next, .last | `DetroitLions` |
| `{home_team_short}` | Home team short name | base, .next, .last | `Lions` |
| `{home_team_logo}` | Home team logo URL | base, .next, .last | ESPN logo URL |
| `{away_team}` | Away team name (positional) | base, .next, .last | `Chicago Bears` |
| `{away_team_abbrev}` | Away team abbreviation uppercase | base, .next, .last | `CHI` |
| `{away_team_abbrev_lower}` | Away team abbreviation lowercase | base, .next, .last | `chi` |
| `{away_team_pascal}` | Away team name in PascalCase | base, .next, .last | `ChicagoBears` |
| `{away_team_short}` | Away team short name | base, .next, .last | `Bears` |
| `{away_team_logo}` | Away team logo URL | base, .next, .last | ESPN logo URL |
| `{is_home}` | 'true' if team is home, 'false' if away | base, .next, .last | `true` |
| `{is_away}` | 'true' if team is away, 'false' if home | base, .next, .last | `false` |
| `{home_away_text}` | 'at home' or 'on the road' | base, .next, .last | `at home` |
| `{vs_at}` | 'vs' if home, 'at' if away | base, .next, .last | `vs` |
| `{vs_@}` | 'vs' if home, '@' if away | base, .next, .last | `vs` |

### Feed Team

When a channel is configured for a specific home or away broadcast feed (via the Feed Separation setting), these variables resolve to the team whose feed this channel carries — independent of which team is home or away on any given day. If the channel has no feed assignment, all Feed Team variables return empty strings (they disappear gracefully from templates).

These are most useful for Event EPG templates on stream-separated channels (e.g., an MLB "Home feed" channel that always shows the home broadcaster's perspective regardless of which team is home today).

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{feed_team}` | Feed team full name | base | `Baltimore Orioles` |
| `{feed_team_short}` | Feed team short name | base | `Orioles` |
| `{feed_team_abbrev}` | Feed team abbreviation uppercase | base | `BAL` |
| `{feed_team_abbrev_lower}` | Feed team abbreviation lowercase | base | `bal` |
| `{feed_team_logo}` | Feed team logo URL | base | ESPN logo URL |
| `{is_home_feed}` | `'true'` if this channel is the home team's feed, `'false'` if away, `''` if no feed | base | `true` |
| `{is_away_feed}` | `'true'` if this channel is the away team's feed, `'false'` if home, `''` if no feed | base | `false` |
| `{feed_home_away}` | `'Home'` if home feed, `'Away'` if away feed, `''` if no feed | base | `Home` |
| `{broadcast_feed}` | `'Home Team Feed'` / `'Away Team Feed'` / `''` if no feed | base | `Home Team Feed` |
| `{broadcast_feed_team}` | `'{Team Name} Feed'` or `''` if no feed | base | `Baltimore Orioles Feed` |

Feed Team variables do **not** support `.next` / `.last` suffixes — they describe the channel's configuration, not a specific game's schedule. For per-game home/away references, use the `{home_team}` / `{away_team}` variables above.

`{broadcast_feed}` and `{broadcast_feed_team}` are **pre-formatted** — they include the literal `" Feed"` suffix. When feed separation isn't active they return `""` as a unit, so the whole phrase disappears cleanly from the template (unlike composing `{feed_home_away} Team Feed` yourself, which would leave `"Team Feed"` orphaned).

---

## Records

Team and opponent win-loss records.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{team_record}` | Team's overall record | base | `10-4` |
| `{team_wins}` | Team's total wins | base | `10` |
| `{team_losses}` | Team's total losses | base | `4` |
| `{team_ties}` | Team's total ties/draws | base | `` |
| `{team_win_pct}` | Team's winning percentage | base | `.714` |
| `{home_record}` | Team's home record | base | `6-1` |
| `{home_win_pct}` | Team's home winning percentage | base | `.857` |
| `{away_record}` | Team's away/road record | base | `4-3` |
| `{away_win_pct}` | Team's away winning percentage | base | `.571` |
| `{opponent_record}` | Opponent's overall record | base, .next, .last | `8-6` |
| `{opponent_wins}` | Opponent's total wins | base, .next, .last | `8` |
| `{opponent_losses}` | Opponent's total losses | base, .next, .last | `6` |
| `{opponent_ties}` | Opponent's total ties/draws | base, .next, .last | `` |
| `{opponent_win_pct}` | Opponent's winning percentage | base, .next, .last | `.571` |
| `{home_team_record}` | Home team's overall record for this game | base, .next, .last | `10-4` |
| `{away_team_record}` | Away team's overall record for this game | base, .next, .last | `8-6` |
| `{home_team_seed}` | Home team's playoff seed | base, .next, .last | `2` |
| `{away_team_seed}` | Away team's playoff seed | base, .next, .last | `5` |

---

## Streaks

Current winning and losing streaks.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{streak}` | Team's current streak formatted (e.g., 'W3' or 'L2') | base | `W2` |
| `{streak_length}` | Team's streak as absolute value | base | `2` |
| `{streak_type}` | Team's streak direction: 'win' or 'loss' | base | `win` |
| `{win_streak}` | Team's winning streak length (empty if losing) | base | `2` |
| `{loss_streak}` | Team's losing streak length (empty if winning) | base | `` |
| `{opponent_streak}` | Opponent's current streak formatted | base, .next, .last | `L1` |
| `{opponent_streak_length}` | Opponent's streak as absolute value | base, .next, .last | `1` |
| `{opponent_streak_type}` | Opponent's streak direction | base, .next, .last | `loss` |
| `{opponent_win_streak}` | Opponent's winning streak (empty if losing) | base, .next, .last | `` |
| `{opponent_loss_streak}` | Opponent's losing streak (empty if winning) | base, .next, .last | `1` |
| `{home_team_streak}` | Home team's current streak formatted | base, .next, .last | `W2` |
| `{home_team_streak_length}` | Home team's streak as absolute value | base, .next, .last | `2` |
| `{home_team_win_streak}` | Home team's winning streak (empty if losing) | base, .next, .last | `2` |
| `{home_team_loss_streak}` | Home team's losing streak (empty if winning) | base, .next, .last | `` |
| `{away_team_streak}` | Away team's current streak formatted | base, .next, .last | `L1` |
| `{away_team_streak_length}` | Away team's streak as absolute value | base, .next, .last | `1` |
| `{away_team_win_streak}` | Away team's winning streak (empty if losing) | base, .next, .last | `` |
| `{away_team_loss_streak}` | Away team's losing streak (empty if winning) | base, .next, .last | `1` |

---

## Scores

Game scores and results. Empty for future games.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{team_score}` | Team's score (empty if game not started) | base, .next, .last | `31` |
| `{opponent_score}` | Opponent's score (empty if game not started) | base, .next, .last | `24` |
| `{score}` | Score (e.g., '24-17'). Empty if not started. | base, .next, .last | `31-24` |
| `{final_score}` | Score with team perspective (team score first) | base, .next, .last | `31-24` |
| `{home_team_score}` | Home team's score | base, .next, .last | `31` |
| `{away_team_score}` | Away team's score | base, .next, .last | `24` |
| `{score_diff}` | Score differential (+7 = won by 7, -7 = lost by 7) | base, .next, .last | `+7` |
| `{score_differential}` | Score differential as absolute value | base, .next, .last | `7` |
| `{score_differential_text}` | Score differential as text | base, .next, .last | `by 7` |
| `{event_result}` | Full event result. Empty if not final. | base, .next, .last | `Detroit Lions 31 - Chicago Bears 24` |
| `{event_result_abbrev}` | Abbreviated event result. Empty if not final. | base, .next, .last | `DET 31 - CHI 24` |
| `{winner}` | Winning team name. Empty if not final or tie. | base, .next, .last | `Detroit Lions` |
| `{winner_abbrev}` | Winning team abbreviation. Empty if not final or tie. | base, .next, .last | `DET` |
| `{loser}` | Losing team name. Empty if not final or tie. | base, .next, .last | `Chicago Bears` |
| `{loser_abbrev}` | Losing team abbreviation. Empty if not final or tie. | base, .next, .last | `CHI` |

---

## Outcome

Game result indicators. Empty for future games.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{result}` | Game result ('W', 'L', or 'T') | base, .next, .last | `W` |
| `{result_lower}` | Game result lowercase ('w', 'l', or 't') | base, .next, .last | `w` |
| `{result_text}` | Game result as text ('defeated', 'lost to', 'tied') | base, .next, .last | `defeated` |
| `{overtime_text}` | 'in overtime' if game went to overtime, empty otherwise | base, .next, .last | `` |
| `{overtime_short}` | 'OT' if game went to overtime, empty otherwise | base, .next, .last | `` |

---

## Standings

Playoff position and standings information.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{playoff_seed}` | Team's playoff seed (e.g., '1' for 1-seed) | base | `2` |
| `{games_back}` | Games behind division/conference leader | base | `-` |
| `{opponent_playoff_seed}` | Opponent's playoff seed | base, .next, .last | `5` |
| `{opponent_games_back}` | Opponent's games behind leader | base, .next, .last | `-` |

---

## Statistics

Team scoring averages.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{team_ppg}` | Team's points per game average | base | `28.4` |
| `{team_papg}` | Team's points allowed per game average | base | `21.6` |
| `{opponent_ppg}` | Opponent's points per game average | base, .next, .last | `24.2` |
| `{opponent_papg}` | Opponent's points allowed per game average | base, .next, .last | `22.8` |
| `{home_team_ppg}` | Home team's PPG for this game | base, .next, .last | `28.4` |
| `{away_team_ppg}` | Away team's PPG for this game | base, .next, .last | `24.2` |

---

## Playoffs

Season type indicators. All providers normalize their native season codes to a canonical value so these variables behave consistently regardless of the underlying data source.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{season_type}` | Canonical season type — one of `preseason`, `regular`, `postseason`, `offseason`, or empty if unknown | base, .next, .last | `postseason` |
| `{is_playoff}` | `'true'` if postseason game | base, .next, .last | `` |
| `{is_preseason}` | `'true'` if preseason/exhibition game | base, .next, .last | `` |
| `{is_regular_season}` | `'true'` if regular season game | base, .next, .last | `true` |

**Provider coverage:**

| Provider | Playoff detection |
|----------|-------------------|
| ESPN | Full — derived from season slug (`post-season`, `semifinals`, etc.) with numeric-type fallback |
| MLB Stats | Full — `gameType` codes (`F`/`D`/`L`/`W`/`P` → postseason, `S`/`E` → preseason) |
| HockeyTech | Full — via per-season `playoff` flag (CHL, AHL, PWHL, USHL) |
| TSDB | Partial — postseason detected via special `intRound` codes (125/150/160/170/180/200) used by some leagues (NBA, NHL, IPL, European knockouts). Leagues that keep normal round numbering through finals (AFL, NRL, boxing) can't be detected and return empty. Preseason is never detected for TSDB. |

---

## Odds

Betting lines and odds (when available).

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{has_odds}` | 'true' if odds are available for this game | base, .next | `true` |
| `{odds_spread}` | Point spread | base, .next | `-3.0` |
| `{odds_moneyline}` | Team's moneyline (e.g., '-150' or '+130') | base, .next | `-150` |
| `{odds_opponent_moneyline}` | Opponent's moneyline | base, .next | `+130` |
| `{odds_over_under}` | Over/under total (e.g., '47.5') | base, .next | `48.5` |
| `{odds_provider}` | Odds provider name | base, .next | `ESPN BET` |
| `{odds_details}` | Full odds description string | base, .next | `DET -3.0, O/U 48.5` |

---

## Broadcast

TV and streaming information.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{broadcast_network}` | Primary broadcast network (first in list) | base, .next, .last | `FOX` |
| `{broadcast_simple}` | Comma-separated broadcast networks | base, .next, .last | `FOX, NFL Network` |
| `{broadcast_national_network}` | National broadcast networks only | base, .next, .last | `FOX` |
| `{is_national_broadcast}` | 'true' if game is on national TV | base, .next, .last | `true` |

---

## Rankings

College rankings (NCAAF, NCAAM, NCAAW).

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{team_rank}` | Team's ranking (e.g., '5' for #5, empty if unranked) | base | `` |
| `{team_rank_display}` | Team's ranking with # prefix (e.g., '#5') | base | `` |
| `{is_ranked}` | 'true' if team is ranked, empty otherwise | base | `` |
| `{opponent_rank}` | Opponent's ranking | base, .next, .last | `` |
| `{opponent_rank_display}` | Opponent's ranking with # prefix | base, .next, .last | `` |
| `{opponent_is_ranked}` | 'true' if opponent is ranked, empty otherwise | base, .next, .last | `` |
| `{is_ranked_matchup}` | 'true' if both teams are ranked | base, .next, .last | `` |
| `{home_team_rank}` | Home team's ranking for this game | base, .next, .last | `` |
| `{away_team_rank}` | Away team's ranking for this game | base, .next, .last | `` |

---

## Conference

Conference and division information.

### Pro Leagues

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{pro_conference}` | Team's pro conference (e.g., 'NFC', 'Eastern') | base | `NFC` |
| `{pro_conference_abbrev}` | Team's pro conference abbreviation | base | `NFC` |
| `{pro_division}` | Team's pro division (e.g., 'NFC North') | base | `NFC North` |
| `{opponent_pro_conference}` | Opponent's pro conference | base, .next, .last | `NFC` |
| `{opponent_pro_conference_abbrev}` | Opponent's pro conference abbreviation | base, .next, .last | `NFC` |
| `{opponent_pro_division}` | Opponent's pro division | base, .next, .last | `NFC North` |
| `{home_team_pro_conference}` | Home team's pro conference | base, .next, .last | `NFC` |
| `{home_team_pro_conference_abbrev}` | Home team's pro conference abbreviation | base, .next, .last | `NFC` |
| `{home_team_pro_division}` | Home team's pro division | base, .next, .last | `NFC North` |
| `{away_team_pro_conference}` | Away team's pro conference | base, .next, .last | `NFC` |
| `{away_team_pro_conference_abbrev}` | Away team's pro conference abbreviation | base, .next, .last | `NFC` |
| `{away_team_pro_division}` | Away team's pro division | base, .next, .last | `NFC North` |

### College Leagues

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{college_conference}` | Team's college conference name | base | `` |
| `{college_conference_abbrev}` | Team's college conference abbreviation | base | `` |
| `{opponent_college_conference}` | Opponent's college conference | base, .next, .last | `` |
| `{opponent_college_conference_abbrev}` | Opponent's college conference abbreviation | base, .next, .last | `` |
| `{home_team_college_conference}` | Home team's college conference | base, .next, .last | `` |
| `{home_team_college_conference_abbrev}` | Home team's college conference abbreviation | base, .next, .last | `` |
| `{away_team_college_conference}` | Away team's college conference | base, .next, .last | `` |
| `{away_team_college_conference_abbrev}` | Away team's college conference abbreviation | base, .next, .last | `` |

---

## Soccer

Soccer-specific variables for teams that play in multiple competitions.

| Variable | Description | Suffixes | Sample |
|----------|-------------|----------|--------|
| `{soccer_primary_league}` | Team's home league name (e.g., 'Premier League') | base | `` |
| `{soccer_primary_league_id}` | Team's home league ID (e.g., 'eng.1') | base | `` |
| `{soccer_match_league}` | League for THIS game (may differ from primary) | base, .next, .last | `` |
| `{soccer_match_league_id}` | League ID for THIS game (e.g., 'uefa.champions') | base, .next, .last | `` |
| `{soccer_match_league_logo}` | Logo URL for THIS game's league | base, .next, .last | `` |

{: .note }
Soccer teams often play in multiple competitions (domestic league, cups, Champions League). The `soccer_match_league` variables tell you which competition a specific game is in, while `soccer_primary_league` is the team's home league.

---

## Combat Sports

UFC and MMA-specific variables for event templates. These are **event-only** (no `.next`/`.last` suffixes) since each UFC event is independent.

### Fighters & Matchup

| Variable | Description | Sample |
|----------|-------------|--------|
| `{fighter1}` | First fighter name (headline bout) | `Alex Volkanovski` |
| `{fighter2}` | Second fighter name (headline bout) | `Diego Lopes` |
| `{matchup}` | Full matchup string | `Alex Volkanovski vs Diego Lopes` |
| `{event_number}` | UFC event number (e.g., '314' from 'UFC 314') | `314` |
| `{event_title}` | Full event title | `UFC 314: Volkanovski vs Lopes` |

### Card Segments

| Variable | Description | Sample |
|----------|-------------|--------|
| `{card_segment}` | Segment code for this channel | `main_card` |
| `{card_segment_display}` | Human-readable segment name | `Main Card` |
| `{main_card_time}` | Main card start time | `10:00 PM EST` |
| `{prelims_time}` | Prelims start time | `8:00 PM EST` |
| `{early_prelims_time}` | Early prelims start time | `6:00 PM EST` |

### Fight Card

| Variable | Description | Sample |
|----------|-------------|--------|
| `{bout_count}` | Total number of bouts on the card | `14` |
| `{fight_card}` | All bouts (newline-separated) | `Alex Volkanovski vs Diego Lopes`<br>`Merab Dvalishvili vs Umar Nurmagomedov` |
| `{main_card_bouts}` | Main card bouts only | `Alex Volkanovski vs Diego Lopes`<br>`Merab Dvalishvili vs Umar Nurmagomedov` |
| `{prelims_bouts}` | Prelims bouts only | `Sean Brady vs Kelvin Gastelum`<br>`Chris Weidman vs Eryk Anders` |
| `{early_prelims_bouts}` | Early prelims bouts only | `Mauricio Ruffy vs Jamie Mullarkey` |

{: .note }
UFC events are split into segments (Early Prelims, Prelims, Main Card). When using segment-based channel routing, each channel gets a `{card_segment}` value indicating which segment it covers. The `{fighter1}` and `{fighter2}` variables always refer to the headline (main event) bout.

---

## Motorsports

F1, NASCAR, IndyCar, and MotoGP-specific variables for event templates. These are **event-only** (no `.next`/`.last` suffixes) since each race weekend is independent.

### Event & Circuit

| Variable | Description | Sample |
|----------|-------------|--------|
| `{race_name}` | Race weekend / Grand Prix name | `Monaco Grand Prix` |
| `{circuit_name}` | Circuit/track name | `Circuit de Monaco` |

### Sessions

| Variable | Description | Sample |
|----------|-------------|--------|
| `{session_name}` | This channel's session display name | `Practice 1`, `Qualifying`, `Race` |
| `{session_type}` | This channel's session code | `fp1`, `qualifying`, `race` |
| `{next_session_name}` | Display name of the next session | `Qualifying` |
| `{next_session_time}` | Start time of the next session | `9:00 AM` |

### Grid & Qualifying

| Variable | Description | Sample |
|----------|-------------|--------|
| `{pole_position}` | Driver who took pole position | `Max Verstappen` |
| `{pole_team}` | Team/constructor of the pole sitter | `Red Bull Racing` |
| `{grid}` | Full starting grid order (newline-separated) | `1. Max Verstappen (Red Bull Racing)`<br>`2. Charles Leclerc (Ferrari)` |

### Results

| Variable | Description | Sample |
|----------|-------------|--------|
| `{race_winner}` | Race winner's name | `Max Verstappen` |
| `{podium_2}` | 2nd place finisher | `Charles Leclerc` |
| `{podium_3}` | 3rd place finisher | `Lewis Hamilton` |
| `{podium}` | Top 3 finishers, combined | `1. Max Verstappen, 2. Charles Leclerc, 3. Lewis Hamilton` |
| `{results}` | Full finishing order (newline-separated) | `1. Max Verstappen (Red Bull Racing)`<br>`2. Charles Leclerc (Ferrari)` |
| `{fastest_lap_driver}` | Driver awarded fastest lap | `Lando Norris` |

{: .note }
Race weekends are split into per-session channels (Practice 1/2/3, Qualifying, Sprint, Race). Each channel gets a `{session_type}`/`{session_name}` value indicating which session it covers. Grid and results variables read from the qualifying and race sessions respectively, and are empty until those sessions have data.

---

## Usage Examples

### Team Template (Detroit Lions channel)

```
Title: {team_name} {vs_at} {opponent}
→ "Detroit Lions vs Chicago Bears"

Description: The {team_name} ({team_record}) host the {opponent} ({opponent_record}) at {venue}. {today_tonight_title}'s game airs on {broadcast_network}.
→ "The Detroit Lions (10-4) host the Chicago Bears (8-6) at Ford Field. Today's game airs on FOX."
```

### Event Template (game-specific channel)

```
Title: {away_team} @ {home_team}
→ "Chicago Bears @ Detroit Lions"

Description: {away_team} ({away_team_record}) at {home_team} ({home_team_record}). {home_team} is a {odds_spread} favorite.
→ "Chicago Bears (8-6) at Detroit Lions (10-4). Detroit Lions is a -3.0 favorite."
```

### Postgame Filler (team template)

```
Title: {team_name} Postgame
Description: The {team_name} {result_text.last} the {opponent.last} {final_score.last} {overtime_text.last}.
→ "The Detroit Lions defeated the Minnesota Vikings 28-21."
```

### UFC Event Template

```
Title: {event_title} - {card_segment_display}
→ "UFC 314: Volkanovski vs Lopes - Main Card"

Description: {matchup}. Main card at {main_card_time}. {bout_count} total bouts.
→ "Alex Volkanovski vs Diego Lopes. Main card at 10:00 PM EST. 14 total bouts."
```
