"""Squiggle AFL API HTTP client.

Handles raw HTTP requests to https://api.squiggle.com.au/.
No data transformation — just fetch and return JSON.

Usage policy (from https://api.squiggle.com.au/):
- Set a descriptive UserAgent identifying the bot
- Cache and reuse data — do not spam identical requests
- Avoid large numbers of simultaneous requests

We satisfy these by:
- Setting SQUIGGLE_USER_AGENT in every request
- Caching the season schedule in-process via TTLCache
"""
import logging
import threading

import httpx

from teamarr.utilities.cache import TTLCache, make_cache_key

logger = logging.getLogger(__name__)

BASE_URL = "https://api.squiggle.com.au/"
_SQUIGGLE_DOMAIN = "https://squiggle.com.au"
_LOGO_FALLBACK_PATH = "/wp-content/themes/squiggle/assets/images/"

# Squiggle requires a descriptive UserAgent (see API docs)
USER_AGENT = "Teamarr/2 (https://github.com/Pharaoh-Labs/teamarr)"

# Cache TTLs
_TTL_GAMES = 60 * 60        # 1 hour — season schedule changes infrequently
_TTL_TEAMS = 24 * 60 * 60   # 24 hours — 18 teams, never changes mid-season
_TTL_STANDINGS = 6 * 60 * 60  # 6 hours — ladder updates once per round (~weekly)


class SquiggleClient:
    """Low-level Squiggle API client with in-process caching.

    Squiggle has no hard rate limits but requires caching and a proper
    UserAgent. We fetch the full season schedule once per hour and filter
    in-process rather than making per-round or per-date API calls.
    """

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._http: httpx.Client | None = None
        self._lock = threading.Lock()
        self._cache = TTLCache()

    def _get_http(self) -> httpx.Client:
        if self._http is None:
            with self._lock:
                if self._http is None:
                    self._http = httpx.Client(
                        timeout=self._timeout,
                        headers={"User-Agent": USER_AGENT},
                    )
        return self._http

    def _get(self, params: dict) -> dict | None:
        url = BASE_URL
        try:
            resp = self._get_http().get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "[SQUIGGLE] HTTP %d for %s params=%s", e.response.status_code, url, params
            )
        except Exception as e:
            logger.warning("[SQUIGGLE] Request failed params=%s: %s", params, e)
        return None

    def get_teams(self) -> list[dict]:
        """Fetch all 18 AFL teams. Cached for 24 hours."""
        cache_key = make_cache_key("squiggle", "teams")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        data = self._get({"q": "teams"})
        teams = (data or {}).get("teams") or []
        if teams:
            self._cache.set(cache_key, teams, _TTL_TEAMS)
        return teams

    def get_games(self, year: int) -> list[dict]:
        """Fetch all games for a season. Cached for 1 hour.

        Returns the full season schedule (~216 games for AFL). Callers
        should filter by date or team in-process rather than making
        additional API calls.
        """
        cache_key = make_cache_key("squiggle", "games", str(year))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        data = self._get({"q": "games", "year": year})
        games = (data or {}).get("games") or []
        if games:
            self._cache.set(cache_key, games, _TTL_GAMES)
            logger.debug("[SQUIGGLE] Fetched %d games for year=%d", len(games), year)
        return games

    def get_standings(self, year: int) -> list[dict]:
        """Fetch ladder/standings for a season. Cached for 6 hours.

        Returns one entry per team with: id, name, rank, wins, losses, draws,
        played, for, against, pts, percentage.
        """
        cache_key = make_cache_key("squiggle", "standings", str(year))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        data = self._get({"q": "standings", "year": year})
        standings = (data or {}).get("standings") or []
        if standings:
            self._cache.set(cache_key, standings, _TTL_STANDINGS)
            logger.debug(
                "[SQUIGGLE] Fetched standings for year=%d (%d teams)", year, len(standings)
            )
        return standings

    @staticmethod
    def logo_url(path: str) -> str:
        """Construct full logo URL from the logo field returned by the teams API.

        The API returns either a full relative path (/wp-content/...) or just
        a filename. Both are handled here.
        """
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("/"):
            return f"{_SQUIGGLE_DOMAIN}{path}"
        return f"{_SQUIGGLE_DOMAIN}{_LOGO_FALLBACK_PATH}{path}"
