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

# UFC athlete endpoint (for fighter profiles)
ESPN_UFC_ATHLETE_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/athletes"

COLLEGE_SCOREBOARD_GROUPS = {
    "mens-college-basketball": "50",
    "womens-college-basketball": "50",
    # Note: college-football omitted to return both FBS + FCS games
    # Note: mens-college-hockey does NOT need groups param
}

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
        )

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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/scoreboard"
        params: dict = {"dates": date_str} if date_str else {}

        if league in COLLEGE_SCOREBOARD_GROUPS:
            params["groups"] = COLLEGE_SCOREBOARD_GROUPS[league]

        return self._request(url, params)

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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/scoreboard"

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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/teams/{team_id}/schedule"
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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/teams/{team_id}"
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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/summary"
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
        url = f"{ESPN_BASE_URL}/{sport}/{espn_league}/teams"
        return self._request(url, {"limit": 1000})

    # UFC-specific endpoints

    def get_ufc_scoreboard(self) -> dict | None:
        """Fetch UFC scoreboard with correct bout times.

        The scoreboard endpoint returns accurate segment times, unlike the
        app API which is 3 hours off.

        Returns:
            Raw ESPN scoreboard response or None on error
        """
        url = f"{ESPN_BASE_URL}/mma/ufc/scoreboard"
        return self._request(url)

    def get_fighter(self, fighter_id: str) -> dict | None:
        """Fetch UFC fighter profile.

        Args:
            fighter_id: ESPN fighter/athlete ID

        Returns:
            Raw ESPN response or None on error
        """
        url = f"{ESPN_UFC_ATHLETE_URL}/{fighter_id}"
        return self._request(url)

    def get_fighter_record(self, fighter_id: str) -> dict | None:
        """Fetch UFC fighter record (W-L-D with breakdown).

        Args:
            fighter_id: ESPN fighter/athlete ID

        Returns:
            Raw ESPN response with record data or None on error
        """
        url = f"{ESPN_UFC_ATHLETE_URL}/{fighter_id}/records"
        return self._request(url)
