"""HTTP client for Bell Media's public sports widgets API.

The API is undocumented. Its endpoints and parameters are derived from TSN's
public scores widget, so callers must remain conservative and cache responses.
"""

import logging
from datetime import date

from teamarr.core.interfaces import LeagueMapping, LeagueMappingSource
from teamarr.providers.base_client import BaseHTTPClient
from teamarr.utilities.cache import TTLCache, make_cache_key

logger = logging.getLogger(__name__)

BELLMEDIA_BASE_URL = "https://next-gen.sports.bellmedia.ca/v2"
_PARAMS = {"brand": "tsn", "lang": "en"}
_TTL_TEAMS = 24 * 60 * 60
_TTL_CALENDAR = 24 * 60 * 60
_TTL_SCHEDULE = 30 * 60
_TTL_EVENT = 30 * 60


class BellMediaClient(BaseHTTPClient):
    """Fetch sports data from the Bell Media API used by TSN's score pages."""

    PROVIDER = "bellmedia"
    LOG_TAG = "BELLMEDIA"

    def __init__(
        self,
        league_mapping_source: LeagueMappingSource | None = None,
        timeout: float = 10.0,
        retry_count: int = 3,
    ):
        super().__init__(timeout=timeout, retry_count=retry_count)
        self._league_mapping_source = league_mapping_source
        self._cache = TTLCache()

    def supports_league(self, league: str) -> bool:
        return bool(
            self._league_mapping_source
            and self._league_mapping_source.supports_league(league, self.PROVIDER)
        )

    def get_mapping(self, league: str) -> LeagueMapping | None:
        if not self._league_mapping_source:
            return None
        return self._league_mapping_source.get_mapping(league, self.PROVIDER)

    def _request_for_mapping(
        self,
        mapping: LeagueMapping,
        path: str,
        params: dict | None = None,
        *,
        label: str,
    ) -> dict | list | None:
        query = dict(_PARAMS)
        if params:
            query.update(params)
        endpoint = path.format(sport=mapping.sport, league=mapping.provider_league_id)
        return self._request_json(f"{BELLMEDIA_BASE_URL}/{endpoint}", query, label=label)

    def get_competitors(self, league: str) -> list[dict]:
        mapping = self.get_mapping(league)
        if not mapping:
            return []
        cache_key = make_cache_key(self.PROVIDER, "competitors", league)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        data = self._request_for_mapping(
            mapping,
            "competitor/{sport}/{league}",
            label="competitors",
        )
        competitors = data if isinstance(data, list) else []
        if competitors:
            self._cache.set(cache_key, competitors, _TTL_TEAMS)
        return competitors

    def get_calendar(self, league: str) -> dict:
        mapping = self.get_mapping(league)
        if not mapping:
            return {}
        cache_key = make_cache_key(self.PROVIDER, "calendar", league)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        data = self._request_for_mapping(
            mapping,
            "leagueCalendar/sports/{sport}/leagues/{league}",
            label="league-calendar",
        )
        calendar = data if isinstance(data, dict) else {}
        if calendar:
            self._cache.set(cache_key, calendar, _TTL_CALENDAR)
        return calendar

    def get_schedule_group(self, league: str, grouping: int, season: int | None) -> list[dict]:
        mapping = self.get_mapping(league)
        if not mapping:
            return []
        cache_key = make_cache_key(self.PROVIDER, "schedule", league, str(grouping), str(season))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        params: dict[str, int] = {"grouping": grouping, "nbDaysOrWeeksToShow": 1}
        if season is not None:
            params["season"] = season
        data = self._request_for_mapping(
            mapping,
            "schedule/sports/{sport}/leagues/{league}",
            params,
            label="schedule",
        )
        events = [
            event
            for group in (data or {}).values()
            for event in group
            if isinstance(event, dict)
        ]
        if events:
            self._cache.set(cache_key, events, _TTL_SCHEDULE)
        return events

    def get_events_between(self, league: str, start: date, end: date) -> list[dict]:
        calendar = self.get_calendar(league)
        season = calendar.get("season")
        groups = calendar.get("weeklyCalendar") or {}
        grouping_ids = {
            int(group_id)
            for group_id, group in groups.items()
            if (group.get("startDate") or "") <= end.isoformat()
            and (group.get("endDate") or "") >= start.isoformat()
        }
        events: list[dict] = []
        for grouping in sorted(grouping_ids):
            events.extend(self.get_schedule_group(league, grouping, season))
        return events

    def get_event(self, league: str, event_id: str) -> dict | None:
        mapping = self.get_mapping(league)
        if not mapping or not str(event_id).isdigit():
            return None
        cache_key = make_cache_key(self.PROVIDER, "event", league, str(event_id))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        data = self._request_for_mapping(
            mapping,
            "event/{sport}/{league}/" + str(event_id),
            label="event",
        )
        event = data if isinstance(data, dict) else None
        if event:
            self._cache.set(cache_key, event, _TTL_EVENT)
        return event
