"""ESPN API HTTP client.

Handles raw HTTP requests to ESPN endpoints.
No data transformation - just fetch and return JSON.

Configuration via environment variables:
    ESPN_MAX_CONNECTIONS: Max concurrent connections (default: 100)
    ESPN_TIMEOUT: Request timeout in seconds (default: 10)
    ESPN_RETRY_COUNT: Number of retry attempts (default: 3)
"""

import logging
import os

from teamarr.providers.base_client import BaseHTTPClient

logger = logging.getLogger(__name__)

# Environment variable configuration with defaults
# These allow users with DNS throttling (PiHole, AdGuard) to tune performance
ESPN_MAX_CONNECTIONS = int(os.environ.get("ESPN_MAX_CONNECTIONS", 100))
ESPN_TIMEOUT = float(os.environ.get("ESPN_TIMEOUT", 10.0))
ESPN_RETRY_COUNT = int(os.environ.get("ESPN_RETRY_COUNT", 3))

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_CORE_URL = "http://sports.core.api.espn.com/v2/sports"
ESPN_USER_AGENT = "curl/8.7.1"

# UFC athlete endpoint (for fighter profiles)
ESPN_UFC_ATHLETE_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes"

# ESPN's ungrouped NCAA scoreboards can omit entire divisions. Fetch the root
# groups and merge their slates so a canonical Teamarr league covers all NCAA
# events ESPN exposes, including cross-division fixtures.
#
# Never send `limit` on these requests (#625). Measured 2026-08-28 against the
# busiest days of the year: with no limit ESPN returns the whole slate (143
# MBB, 121 WBB, 117 CFB); limit=100 truncates to 100; 200-500 return the whole
# slate; and any limit ABOVE 500 — 1000 included — makes ESPN silently return
# exactly 25 events. That single parameter cut Week 1 FBS coverage from 68
# games to 17. `_SCOREBOARD_CAP_CANARY` warns if that shape ever comes back.
_SCOREBOARD_CAP_CANARY = 25

COLLEGE_SCOREBOARD_GROUPS: dict[str, tuple[str, ...]] = {
    "college-football": ("90", "35"),  # Division I; Division II/III
    "mens-college-basketball": ("50", "51"),  # NCAA D-I; non-NCAA D-I
    "womens-college-basketball": ("50", "51"),
    "college-baseball": ("26",),
    "college-softball": ("31",),
    "mens-college-volleyball": ("90",),
    "womens-college-volleyball": ("90", "91", "110"),
    "mens-college-lacrosse": ("90",),
    "womens-college-lacrosse": ("90", "108"),
    # NCAA hockey's ungrouped endpoint already returns its complete slate.
    # NCAA soccer and women's hockey expose no season groups.
}

# ESPN publishes poll rankings only for college leagues — /rankings 404s for
# every pro league (verified 2026-09-04: nfl, usa.1, college-baseball all 404).
# Confirmed to carry polls: college-football (AP / AFCA coaches / FCS coaches /
# D-II), both college basketballs (AP / coaches), college volleyball and
# lacrosse (AVCA, Inside Lacrosse), college hockey (USCHO), and NCAA soccer
# (United Soccer Coaches). college-baseball and college-softball 404 today but
# match the 'college' rule, so they light up on their own if ESPN adds a poll —
# the cost is one 404 per league per cache window.
NCAA_SOCCER_RANKED_SLUGS = frozenset({"usa.ncaa.m.1", "usa.ncaa.w.1"})


def league_publishes_rankings(espn_league: str) -> bool:
    """True when ESPN exposes a /rankings endpoint for this league slug."""
    return "college" in espn_league or espn_league in NCAA_SOCCER_RANKED_SLUGS


# ESPN team ID corrections for known mismatches between /teams endpoint and scoreboard
# Format: (league, wrong_id) -> correct_id
# These are cases where ESPN's /teams endpoint returns a different ID than the scoreboard uses
ESPN_TEAM_ID_CORRECTIONS: dict[tuple[str, str], str] = {
    # Minnesota State Mavericks: /teams returns 2364 (generic school ID), scoreboard uses 24059
    ("womens-college-hockey", "2364"): "24059",
}


class ESPNClient(BaseHTTPClient):
    """Low-level ESPN API client.

    HTTP plumbing (pooled client, retry/backoff, 429 handling) comes from
    BaseHTTPClient. All settings can be tuned via environment variables for
    constrained environments.
    """

    PROVIDER = "espn"
    LOG_TAG = "ESPN"

    def __init__(
        self,
        timeout: float | None = None,
        retry_count: int | None = None,
        max_connections: int | None = None,
    ):
        super().__init__(
            timeout=timeout if timeout is not None else ESPN_TIMEOUT,
            retry_count=retry_count if retry_count is not None else ESPN_RETRY_COUNT,
            max_connections=(
                max_connections if max_connections is not None else ESPN_MAX_CONNECTIONS
            ),
            headers={"User-Agent": ESPN_USER_AGENT},
        )
        self._base_url = ESPN_BASE_URL
        self._core_url = ESPN_CORE_URL
        self._ufc_athlete_url = ESPN_UFC_ATHLETE_URL

    def _request(self, url: str, params: dict | None = None) -> dict | None:
        label = url.split("/sports/")[-1] if "/sports/" in url else url
        return self._request_json(url, params, label=label)

    def get_sport_league(
        self, league: str, override: tuple[str, str] | None = None
    ) -> tuple[str, str]:
        """Convert canonical league to ESPN sport/league pair.

        Args:
            league: Canonical league code (e.g., 'nfl', 'nba')
            override: (sport, league) tuple from database config (required for non-soccer)

        Returns:
            (sport, espn_league) tuple for API path construction
        """
        # Database config is the source of truth
        if override:
            return override
        # Soccer leagues use dot notation - can infer sport
        if "." in league:
            return ("soccer", league)
        # No config provided - log warning and return league as-is
        logger.warning("[ESPN] No database config for league '%s' - add to leagues table", league)
        return ("unknown", league)

    def _correct_team_id(self, league: str, team_id: str) -> str:
        """Apply team ID corrections for known ESPN mismatches.

        Some teams have different IDs in ESPN's /teams endpoint vs scoreboard.
        This maps the wrong ID (from /teams) to the correct ID (from scoreboard).
        """
        corrected = ESPN_TEAM_ID_CORRECTIONS.get((league, team_id))
        if corrected:
            logger.info("[ESPN] Correcting team ID %s -> %s for %s", team_id, corrected, league)
            return corrected
        return team_id

    def get_scoreboard(
        self,
        league: str,
        date_str: str | None = None,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch scoreboard for a league.

        Args:
            league: Canonical league code (e.g., 'nfl', 'nba')
            date_str: Date in YYYYMMDD format. When None, ESPN returns its
                default slate — the most-recent-relevant games, which in the
                offseason is the last completed game (used for sample previews).
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN response or None on error
        """
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/scoreboard"
        params: dict = {"dates": date_str} if date_str else {}
        groups = COLLEGE_SCOREBOARD_GROUPS.get(league)
        if not groups:
            return self._request(url, params)

        responses = []
        for group in groups:
            response = self._request(url, {**params, "groups": group})
            if response is None:
                logger.warning("[ESPN] Empty scoreboard response for %s group %s", league, group)
                continue
            if len(response.get("events", [])) == _SCOREBOARD_CAP_CANARY:
                # A real slate is never exactly 25; this is the shape ESPN
                # returns when it decides to cap a request (see the note on
                # COLLEGE_SCOREBOARD_GROUPS). Surface it rather than silently
                # matching against a fifth of the schedule.
                logger.warning(
                    "[ESPN] %s group %s returned exactly %d events — ESPN may be capping "
                    "this request; coverage is probably incomplete",
                    league,
                    group,
                    _SCOREBOARD_CAP_CANARY,
                )
            responses.append(response)

        if not responses:
            return None
        if len(responses) == 1:
            return responses[0]

        merged = dict(responses[0])
        seen_event_ids: set[str] = set()
        events = []
        for response in responses:
            for event in response.get("events", []):
                event_id = event.get("id")
                if event_id and event_id in seen_event_ids:
                    continue
                if event_id:
                    seen_event_ids.add(event_id)
                events.append(event)
        merged["events"] = events
        return merged

    def get_league_info(
        self,
        league: str,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch league metadata including logo from scoreboard endpoint.

        Args:
            league: Canonical league code (e.g., 'eng.fa', 'uefa.champions')
            sport_league: Optional (sport, league) tuple

        Returns:
            Dict with name, logo_url, abbreviation or None on error
        """
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/scoreboard"

        data = self._request(url)
        if not data:
            return None

        leagues = data.get("leagues", [])
        if not leagues:
            return None

        league_data = leagues[0]
        logo_url = None

        # Extract logo - prefer default, fallback to first
        logos = league_data.get("logos", [])
        for logo in logos:
            rel = logo.get("rel", [])
            if "default" in rel:
                logo_url = logo.get("href")
                break
        if not logo_url and logos:
            logo_url = logos[0].get("href")

        return {
            "name": league_data.get("name"),
            "abbreviation": league_data.get("abbreviation"),
            "logo_url": logo_url,
            "id": league_data.get("id"),
        }

    def get_team_schedule(
        self,
        league: str,
        team_id: str,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch schedule for a specific team.

        Args:
            league: Canonical league code
            team_id: ESPN team ID
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN response or None on error
        """
        team_id = self._correct_team_id(league, team_id)
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/teams/{team_id}/schedule"
        return self._request(url)

    def get_team(
        self,
        league: str,
        team_id: str,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch team information.

        Args:
            league: Canonical league code
            team_id: ESPN team ID
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN response or None on error
        """
        team_id = self._correct_team_id(league, team_id)
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/teams/{team_id}"
        return self._request(url)

    def get_rankings(
        self,
        league: str,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch the league's current poll rankings.

        Only college leagues publish polls; everything else 404s (the caller
        gates on RANKED_LEAGUE_SLUGS so we don't spend the call).

        Args:
            league: Canonical league code
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN rankings response or None on error
        """
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/rankings"
        return self._request(url)

    def get_event(
        self,
        league: str,
        event_id: str,
        sport_league: tuple[str, str] | None = None,
    ) -> dict | None:
        """Fetch a single event by ID.

        Args:
            league: Canonical league code
            event_id: ESPN event ID
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN response or None on error
        """
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/summary"
        return self._request(url, {"event": event_id})

    def get_teams(self, league: str, sport_league: tuple[str, str] | None = None) -> dict | None:
        """Fetch all teams for a league.

        Args:
            league: Canonical league code
            sport_league: Optional (sport, league) tuple from database config

        Returns:
            Raw ESPN response with teams list or None on error
        """
        sport, espn_league = self.get_sport_league(league, sport_league)
        url = f"{self._base_url}/{sport}/{espn_league}/teams"
        return self._request(url, {"limit": 1000})

    # Core-API season-tree endpoints (#91): conference/division groups. The
    # site /groups endpoint is deliberately NOT used — it truncates children
    # at 25 and serves stale membership (verified 2026-07-17, #91 comments).

    def _season_group_url(self, sport: str, espn_league: str, season: int, group_id: str) -> str:
        return (
            f"{self._core_url}/{sport}/leagues/{espn_league}"
            f"/seasons/{season}/types/2/groups/{group_id}"
        )

    def get_season_group(
        self, sport: str, espn_league: str, season: int, group_id: str
    ) -> dict | None:
        """Fetch one season-tree group (id, name, shortName, isConference)."""
        return self._request(self._season_group_url(sport, espn_league, season, group_id))

    def get_season_group_children(
        self, sport: str, espn_league: str, season: int, group_id: str
    ) -> dict | None:
        """Fetch a group's children as $ref items (conferences under a division)."""
        url = self._season_group_url(sport, espn_league, season, group_id) + "/children"
        return self._request(url, {"limit": 100})

    def get_season_group_teams(
        self, sport: str, espn_league: str, season: int, group_id: str
    ) -> dict | None:
        """Fetch a group's team roster as $ref items (ids parseable from URLs)."""
        url = self._season_group_url(sport, espn_league, season, group_id) + "/teams"
        return self._request(url, {"limit": 500})

    # UFC-specific endpoints

    def get_ufc_scoreboard(self, date_str: str | None = None) -> dict | None:
        """Fetch UFC scoreboard with correct bout times.

        The scoreboard endpoint returns accurate segment times, unlike the
        app API which is 3 hours off.

        Args:
            date_str: YYYYMMDD date or YYYYMMDD-YYYYMMDD range. When None,
                ESPN returns ONLY its current featured card — any other card
                is invisible without an explicit date (#345).

        Returns:
            Raw ESPN scoreboard response or None on error
        """
        url = f"{self._base_url}/mma/ufc/scoreboard"
        params: dict = {"dates": date_str} if date_str else {}
        return self._request(url, params)

    def get_fighter(self, fighter_id: str) -> dict | None:
        """Fetch UFC fighter profile.

        Args:
            fighter_id: ESPN fighter/athlete ID

        Returns:
            Raw ESPN response or None on error
        """
        url = f"{self._ufc_athlete_url}/{fighter_id}"
        return self._request(url)

    def get_fighter_record(self, fighter_id: str) -> dict | None:
        """Fetch UFC fighter record (W-L-D with breakdown).

        Args:
            fighter_id: ESPN fighter/athlete ID

        Returns:
            Raw ESPN response with record data or None on error
        """
        url = f"{self._ufc_athlete_url}/{fighter_id}/records"
        return self._request(url)
