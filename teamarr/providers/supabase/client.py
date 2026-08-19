"""Supabase league HTTP client.

Extracts Supabase credentials (URL + API key) dynamically from each league's
public website so they never need to be hardcoded. The extraction result is
cached for 7 days; team logos (embedded in the Vite bundle as hashed assets)
are extracted in the same pass.

Per-league env var overrides skip the website fetch entirely:
    {LEAGUE_CODE_UPPER}_SUPABASE_URL=https://xxx.supabase.co
    {LEAGUE_CODE_UPPER}_SUPABASE_API_KEY=sb_publishable_...

Currently models the CBL (Canadian Baseball League) table schema:
    teams                   — team roster
    schedule_game_overrides — full season schedule (past + future)
    games                   — completed box scores

A second Supabase-backed league needs only a new leagues row in schema.sql
(provider='supabase', provider_league_id='<site URL>'). If that league uses
a different table schema the client will need extension, but credential/logo
extraction is fully reusable.
"""

import logging
import os
import re
from datetime import date, timedelta

import httpx

from teamarr.core.interfaces import LeagueMappingSource
from teamarr.providers.base_client import BaseHTTPClient
from teamarr.utilities import call_metrics
from teamarr.utilities.cache import TTLCache, make_cache_key

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
CACHE_TTL_CREDENTIALS = 7 * 24 * 3600   # 7 days — Vite hash changes on deploy
CACHE_TTL_TEAMS = 72 * 3600             # 72 hours
CACHE_TTL_SCHEDULE = 30 * 60            # 30 minutes
CACHE_TTL_GAMES = 5 * 60                # 5 minutes (live scores)

SUPABASE_TIMEOUT = float(os.environ.get("SUPABASE_TIMEOUT", 10.0))
SUPABASE_RETRY_COUNT = int(os.environ.get("SUPABASE_RETRY_COUNT", 3))

# Browser User-Agent to avoid bot-rejection on league sites
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Days to look back for .last template variable resolution
DAYS_BACK = 7


def _first_word(name: str) -> str:
    """First word of a full team name, lowercased ("Barrie Baycats" -> "barrie").

    Used only for the fallback name-key join; the city it produces does not always
    match the schedule's home/away override (e.g. "Chatham-Kent" -> "chatham-kent"
    vs override "chatham"), which is why game_number is the primary join key.
    """
    return name.split()[0].lower() if name else ""


class SupabaseLeagueClient(BaseHTTPClient):
    """HTTP client for Supabase-backed league websites.

    Handles credential extraction, logo map extraction, and Supabase REST
    API calls. League routing uses LeagueMappingSource; provider_league_id
    in the database holds the website URL to scrape for credentials.

    Keeps a custom ``_get`` (instead of BaseHTTPClient._request_json) because
    callers need the raw Response — credential extraction parses HTML/JS, and
    REST calls inspect status codes themselves.
    """

    PROVIDER = "supabase"
    LOG_TAG = "SUPABASE"

    def __init__(
        self,
        league_mapping_source: LeagueMappingSource | None = None,
        timeout: float = SUPABASE_TIMEOUT,
        retry_count: int = SUPABASE_RETRY_COUNT,
    ):
        super().__init__(
            timeout=timeout,
            retry_count=retry_count,
            max_connections=20,
            max_keepalive_connections=10,
            headers={"User-Agent": _USER_AGENT},
        )
        self._league_mapping_source = league_mapping_source
        self._cache = TTLCache()

    def _get(self, url: str, **kwargs) -> httpx.Response | None:
        for attempt in range(self._retry_count):
            try:
                response = self._get_client().get(url, **kwargs)
                call_metrics.record_call("supabase", url)
                return response
            except (httpx.RequestError, RuntimeError, OSError) as e:
                logger.warning(
                    "[SUPABASE] GET %s failed (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self._retry_count,
                    e,
                )
                if attempt < self._retry_count - 1:
                    continue
        return None

    # ------------------------------------------------------------------
    # League config
    # ------------------------------------------------------------------

    def supports_league(self, league: str) -> bool:
        if not self._league_mapping_source:
            return False
        return self._league_mapping_source.supports_league(league, "supabase")

    def get_league_config(self, league: str) -> tuple[str, str, str] | None:
        """Return (website_url, supabase_url, api_key) for a league.

        website_url comes from provider_league_id in the database.
        supabase_url and api_key are extracted from that site (or env vars).
        """
        if not self._league_mapping_source:
            return None

        mapping = self._league_mapping_source.get_mapping(league, "supabase")
        if not mapping:
            logger.warning("[SUPABASE] No mapping for league: %s", league)
            return None

        website_url = mapping.provider_league_id
        creds = self._get_credentials(website_url, league)
        if not creds:
            logger.warning(
                "[SUPABASE] Could not obtain credentials for %s (%s)",
                league,
                website_url,
            )
            return None

        supabase_url, api_key = creds
        return (website_url, supabase_url, api_key)

    def get_sport(self, league: str) -> str:
        if not self._league_mapping_source:
            return "baseball"
        mapping = self._league_mapping_source.get_mapping(league, "supabase")
        if mapping and mapping.sport:
            return mapping.sport
        cached = self._league_mapping_source.get_league_sport(league)
        return cached if cached else "baseball"

    # ------------------------------------------------------------------
    # Credential extraction
    # ------------------------------------------------------------------

    def _get_credentials(
        self, website_url: str, league: str
    ) -> tuple[str, str] | None:
        """Return (supabase_url, api_key).

        Checks {LEAGUE_UPPER}_SUPABASE_URL / _API_KEY env vars first, then
        the in-memory cache, then extracts from the live website.
        """
        league_upper = league.upper()
        env_url = os.environ.get(f"{league_upper}_SUPABASE_URL", "")
        env_key = os.environ.get(f"{league_upper}_SUPABASE_API_KEY", "")

        if env_url and env_key:
            logger.debug("[SUPABASE] Using env var credentials for %s", league)
            return (env_url, env_key)

        cache_key = make_cache_key("supabase", "creds", website_url)
        cached = self._cache.get(cache_key)
        if cached is not None:
            url, key = cached
            return (env_url or url, env_key or key)

        extracted = self._extract_from_website(website_url)
        if extracted:
            self._cache.set(cache_key, extracted, CACHE_TTL_CREDENTIALS)
            url, key = extracted
            return (env_url or url, env_key or key)

        return None

    def _extract_from_website(self, website_url: str) -> tuple[str, str] | None:
        """Fetch the league website, find the Vite JS bundle, and extract
        the Supabase URL + API key. Also caches the team logo map as a
        side effect so both are extracted in one HTTP pass.
        """
        logger.info("[SUPABASE] Extracting credentials from %s", website_url)

        resp = self._get(website_url)
        if not resp or resp.status_code != 200:
            logger.error(
                "[SUPABASE] Failed to fetch %s: %s",
                website_url,
                resp.status_code if resp else "no response",
            )
            return None

        # Find all <script src="..."> tags
        script_urls = re.findall(r'src="(/assets/[^"]+\.js[^"]*)"', resp.text)
        if not script_urls:
            logger.error("[SUPABASE] No JS bundles found on %s", website_url)
            return None

        base = website_url.rstrip("/")
        for script_path in script_urls:
            bundle_url = f"{base}{script_path}"
            bundle_resp = self._get(bundle_url)
            if not bundle_resp or bundle_resp.status_code != 200:
                continue

            bundle = bundle_resp.text

            supabase_url = self._extract_supabase_url(bundle)
            api_key = self._extract_api_key(bundle)

            if supabase_url and api_key:
                logger.info(
                    "[SUPABASE] Extracted credentials from %s (key: %s...)",
                    bundle_url,
                    api_key[:20],
                )
                # Extract and cache logo map as a side effect
                logo_map = self._extract_logo_map(bundle, base)
                if logo_map:
                    logo_key = make_cache_key("supabase", "logos", website_url)
                    self._cache.set(logo_key, logo_map, CACHE_TTL_CREDENTIALS)
                    logger.debug(
                        "[SUPABASE] Cached %d team logos for %s",
                        len(logo_map),
                        website_url,
                    )
                return (supabase_url, api_key)

        logger.error(
            "[SUPABASE] Could not extract credentials from any bundle on %s",
            website_url,
        )
        return None

    def _extract_supabase_url(self, bundle: str) -> str | None:
        m = re.search(r'(https://[a-z0-9]+\.supabase\.co)', bundle)
        return m.group(1) if m else None

    def _extract_api_key(self, bundle: str) -> str | None:
        # Try new publishable key format first
        m = re.search(r'(sb_publishable_[A-Za-z0-9_-]+)', bundle)
        if m:
            return m.group(1)
        # Fallback: JWT anon key (base64 middle segment must have "anon" role)
        for m in re.finditer(
            r'(eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)',
            bundle,
        ):
            token = m.group(1)
            try:
                import base64
                payload_b64 = token.split(".")[1]
                # Pad to multiple of 4
                padding = 4 - len(payload_b64) % 4
                payload = base64.b64decode(payload_b64 + "=" * padding)
                if b'"anon"' in payload or b'"role":"anon"' in payload:
                    return token
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Logo extraction
    # ------------------------------------------------------------------

    def _get_logo_map(self, website_url: str) -> dict[str, str]:
        """Return {team_id: full_logo_url} map for a league website."""
        logo_key = make_cache_key("supabase", "logos", website_url)
        cached = self._cache.get(logo_key)
        if cached is not None:
            return cached

        # Trigger a full website extraction which caches the logo map
        self._extract_from_website(website_url)

        cached = self._cache.get(logo_key)
        return cached if cached is not None else {}

    def _extract_logo_map(self, bundle: str, base_url: str) -> dict[str, str]:
        """Extract {TEAMID: logo_url} map from a Vite bundle.

        The bundle contains a const block assigning asset paths to variables:
          VarA="/assets/barrie-baycats-HASH.png"
          VarB="/assets/toronto-HASH.png"
          ...
          MAP={BARRIEBAYCATS:VarA, TORONTOMAPLELEAFS:VarB, ...}

        The map variable name (VX, XX, etc.) changes on every deploy so we
        search for any object literal with 3+ ALL_CAPS team-ID keys rather
        than hard-coding a name.
        """
        # Find any assignment of the form VARNAME={ALL_CAPS_KEY:var, ...}
        map_match = re.search(
            r'[A-Za-z_$][A-Za-z0-9_$]*=\{((?:[A-Z]{3,}[A-Z0-9]*:[A-Za-z_$][A-Za-z0-9_$]*,?\s*){3,})\}',
            bundle,
        )
        if not map_match:
            logger.debug("[SUPABASE] Logo map pattern not found in bundle")
            return {}

        map_body = map_match.group(1)
        # Parse TEAMID:VarName pairs
        team_var_pairs = re.findall(r'([A-Z]{3,}[A-Z0-9]*):([A-Za-z_$][A-Za-z0-9_$]*)', map_body)
        if not team_var_pairs:
            return {}

        # Resolve variable names to asset paths in the region before the map
        map_start = map_match.start()
        search_region = bundle[max(0, map_start - 5000): map_start]

        logo_map: dict[str, str] = {}
        for team_id, var_name in team_var_pairs:
            pattern = (
                r'(?<![A-Za-z0-9_$])'
                + re.escape(var_name)
                + r'="(/assets/[^"]+\.(?:png|jpg|svg|webp))"'
            )
            asset_match = re.search(pattern, search_region)
            if asset_match:
                logo_map[team_id] = f"{base_url}{asset_match.group(1)}"

        return logo_map

    # ------------------------------------------------------------------
    # Supabase REST
    # ------------------------------------------------------------------

    def _supabase_get(
        self, supabase_url: str, api_key: str, path: str
    ) -> list[dict]:
        """Make an authenticated Supabase REST GET request."""
        url = f"{supabase_url}/rest/v1/{path}"
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        resp = self._get(url, headers=headers)
        if not resp:
            return []
        if resp.status_code != 200:
            logger.warning(
                "[SUPABASE] REST %s returned HTTP %d", path, resp.status_code
            )
            return []
        try:
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("[SUPABASE] Failed to parse JSON from %s: %s", path, e)
            return []

    def _current_season_year(self) -> int:
        from datetime import datetime
        return datetime.now().year

    # ------------------------------------------------------------------
    # League data methods
    # ------------------------------------------------------------------

    def get_teams(self, league: str) -> list[dict]:
        config = self.get_league_config(league)
        if not config:
            return []
        _, supabase_url, api_key = config

        cache_key = make_cache_key("supabase", "teams", league)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("[SUPABASE] Cache hit: %s", cache_key)
            return cached

        data = self._supabase_get(supabase_url, api_key, "teams?select=*")
        if data:
            self._cache.set(cache_key, data, CACHE_TTL_TEAMS)
            logger.debug("[SUPABASE] Cached %d teams for %s", len(data), league)
        return data

    def get_schedule(self, league: str) -> list[dict]:
        """Get full season schedule from schedule_game_overrides."""
        config = self.get_league_config(league)
        if not config:
            return []
        _, supabase_url, api_key = config

        year = self._current_season_year()
        cache_key = make_cache_key("supabase", "schedule", league, str(year))
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("[SUPABASE] Cache hit: %s", cache_key)
            return cached

        path = (
            f"schedule_game_overrides?select=*"
            f"&season_year=eq.{year}"
            f"&order=game_date_override.asc"
        )
        data = self._supabase_get(supabase_url, api_key, path)
        if data:
            self._cache.set(cache_key, data, CACHE_TTL_SCHEDULE)
            logger.debug(
                "[SUPABASE] Cached %d schedule entries for %s %d",
                len(data),
                league,
                year,
            )
        return data

    def get_completed_games(self, league: str) -> list[dict]:
        """Get completed box scores from the games table."""
        config = self.get_league_config(league)
        if not config:
            return []
        _, supabase_url, api_key = config

        year = self._current_season_year()
        cache_key = make_cache_key("supabase", "games", league, str(year))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        path = (
            f"games?select=id,game_date,away_team_name,home_team_name,"
            f"away_score,home_score"
            f"&season_year=eq.{year}"
        )
        data = self._supabase_get(supabase_url, api_key, path)
        if data:
            self._cache.set(cache_key, data, CACHE_TTL_GAMES)
        return data

    def get_logo_map(self, league: str) -> dict[str, str]:
        """Return {team_id: logo_url} for a league."""
        config = self.get_league_config(league)
        if not config:
            return {}
        website_url, _, _ = config
        return self._get_logo_map(website_url)

    def build_score_map(self, games: list[dict]) -> dict[str, dict]:
        """Build score lookups for merging onto schedule entries.

        Returns ``{"by_number": ..., "by_name": ...}`` where:

        - ``by_number`` maps ``games.schedule_game_number`` -> game. This is the
          authoritative join: the number matches ``schedule_game_overrides.game_number``
          exactly (int), so it disambiguates baseball doubleheaders (same two teams,
          same date — distinct game numbers) and is immune to city-name parsing. In the
          live CBL data every current-season completed game carries this number.
        - ``by_name`` maps ``(game_date, home_city, away_city)`` -> game as a defensive
          fallback for any completed game missing a number. City = first word of the
          full team name; this is fragile (e.g. "Chatham-Kent" vs override "chatham"),
          so it is only consulted when the number lookup misses.
        """
        by_number: dict[int, dict] = {}
        by_name: dict[tuple, dict] = {}
        for game in games:
            number = game.get("schedule_game_number")
            if number is not None:
                by_number[number] = game
            game_date = game.get("game_date")
            home_city = _first_word(game.get("home_team_name", ""))
            if game_date and home_city:
                away_city = _first_word(game.get("away_team_name", ""))
                by_name[(game_date, home_city, away_city)] = game
        return {"by_number": by_number, "by_name": by_name}

    def get_events_by_date(self, league: str, target_date: date) -> list[dict]:
        """Get schedule entries for a specific date, merged with scores."""
        schedule = self.get_schedule(league)
        date_str = target_date.strftime("%Y-%m-%d")
        day_entries = [
            g for g in schedule
            if g.get("game_date_override") == date_str
            and g.get("status") != "postponed"
        ]
        if not day_entries:
            return []

        completed = self.get_completed_games(league)
        score_map = self.build_score_map(completed)
        return self._merge_scores(day_entries, score_map)

    def get_team_schedule(
        self, league: str, team_id: str, days_ahead: int = 14
    ) -> list[dict]:
        """Get schedule for a team, including DAYS_BACK past games."""
        teams = self.get_teams(league)
        city = ""
        for t in teams:
            if t.get("id") == team_id:
                city = (t.get("city") or "").lower()
                break
        if not city:
            logger.warning(
                "[SUPABASE] Team %s not found in league %s", team_id, league
            )
            return []

        today = date.today()
        start_date = today - timedelta(days=DAYS_BACK)
        end_date = today + timedelta(days=days_ahead)

        schedule = self.get_schedule(league)
        team_entries = []
        for entry in schedule:
            away = (entry.get("away_team_override") or "").lower()
            home = (entry.get("home_team_override") or "").lower()
            if city not in (away, home):
                continue
            game_date_str = entry.get("game_date_override")
            if not game_date_str:
                continue
            try:
                game_date = date.fromisoformat(game_date_str)
            except ValueError:
                continue
            if start_date <= game_date <= end_date:
                team_entries.append(entry)

        if not team_entries:
            return []

        completed = self.get_completed_games(league)
        score_map = self.build_score_map(completed)
        return self._merge_scores(team_entries, score_map)

    def _merge_scores(
        self, entries: list[dict], score_map: dict[str, dict]
    ) -> list[dict]:
        """Attach score data from score_map to each schedule entry.

        Joins on ``game_number`` first (exact, doubleheader-safe), falling back to
        the ``(date, home_city, away_city)`` name key only when an entry has no
        number or the number has no matching completed game.
        """
        by_number = score_map.get("by_number", {})
        by_name = score_map.get("by_name", {})
        result = []
        for entry in entries:
            number = entry.get("game_number")
            score = by_number.get(number) if number is not None else None
            if score is None:
                game_date = entry.get("game_date_override", "")
                home_city = (entry.get("home_team_override") or "").lower()
                away_city = (entry.get("away_team_override") or "").lower()
                score = by_name.get((game_date, home_city, away_city))
            if score:
                merged = dict(entry)
                merged["_score"] = score
                result.append(merged)
            else:
                result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Cache / lifecycle
    # ------------------------------------------------------------------

    def cache_stats(self) -> dict:
        return self._cache.stats()

    def clear_cache(self) -> None:
        self._cache.clear()
