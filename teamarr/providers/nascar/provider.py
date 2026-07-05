"""NASCAR public API provider for race schedule data.

Fetches race schedules from cf.nascar.com for the Cup, ORAP (Xfinity),
and Truck series. The API provides full race weekend sessions (practice,
qualifying, race) with precise UTC start times, enabling accurate multi-day
session-window matching via _covers_date in the racing matcher — removing the
need for the lookahead_days workaround used when ESPN is the source (ESPN
returns only the single race competition for NASCAR, with no session detail).

URL patterns (no auth required):
  Cup:   https://cf.nascar.com/cacher/{year}/1/race_list_basic.json
  Other: https://cf.nascar.com/cacher/{year}/race_list_basic.json  (keys: series_2, series_3)
"""

import logging
from datetime import UTC, date, datetime

import httpx

from teamarr.core import (
    Event,
    EventStatus,
    LeagueMappingSource,
    RacingSession,
    SportsProvider,
    Team,
    Venue,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://cf.nascar.com/cacher"

# NASCAR run_type values; 0 = admin/logistics, skip those.
_RUN_PRACTICE = 1
_RUN_QUALIFYING = 2
_RUN_RACE = 3

# League code → (url_suffix, series_key_in_response)
# None series_key means the response is a plain list (Cup).
_LEAGUE_CONFIG: dict[str, tuple[str, str | None]] = {
    "nascar-cup":      ("1/race_list_basic.json", None),
    "nascar-xfinity":  ("race_list_basic.json",   "series_2"),
    "nascar-truck":    ("race_list_basic.json",    "series_3"),
}


def _session_code_and_name(event_name: str, run_type: int) -> tuple[str, str]:
    """Map a NASCAR schedule entry to (session_code, display_name)."""
    if run_type == _RUN_RACE:
        return "race", "Race"

    if run_type == _RUN_QUALIFYING:
        return "qualifying", event_name or "Qualifying"

    # run_type == _RUN_PRACTICE (includes combined practice/qualifying entries)
    name_lower = event_name.lower()
    if "practice 1" in name_lower or "first practice" in name_lower:
        return "fp1", "Practice 1"
    if "practice 2" in name_lower or "second practice" in name_lower:
        return "fp2", "Practice 2"
    if "practice 3" in name_lower or "third practice" in name_lower:
        return "fp3", "Practice 3"
    if "practice 4" in name_lower:
        return "fp4", "Practice 4"
    return "practice", event_name or "Practice"


def _make_abbrev(name: str) -> str:
    words = [w for w in name.split() if len(w) > 2]
    if len(words) >= 2:
        return "".join(w[0].upper() for w in words[:4])
    return name[:6].upper()


class NASCARProvider(SportsProvider):
    """Sports data provider backed by the NASCAR public schedule API.

    Loads the full season schedule for each series on startup and caches
    it in memory. get_events() filters to races with a session on the
    requested date — the same per-session date contract as the TSDB racing
    path, so the racing matcher's _covers_date check works correctly.

    The schedule is loaded lazily on first use and refreshed on a TTL (season
    schedules barely change). A failed or empty load retries much sooner: a
    transient API blip must not pin an empty schedule until the next restart.
    The season year is resolved at load time, so long-running processes roll
    over automatically.
    """

    _CACHE_TTL_SECONDS = 6 * 3600
    _EMPTY_RETRY_SECONDS = 15 * 60

    def __init__(
        self,
        league_mapping_source: LeagueMappingSource | None = None,
        timeout: float = 10.0,
    ):
        self._league_mapping_source = league_mapping_source
        self._timeout = timeout
        self._events_by_league: dict[str, list[Event]] = {}
        self._loaded_at: datetime | None = None

    @property
    def name(self) -> str:
        return "nascar"

    def supports_league(self, league: str) -> bool:
        if league not in _LEAGUE_CONFIG:
            return False
        if not self._league_mapping_source:
            return True
        return self._league_mapping_source.supports_league(league, self.name)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        if not self.supports_league(league):
            return []
        self._ensure_loaded()
        return [
            e for e in self._events_by_league.get(league, [])
            if any(s.start_time.date() == target_date for s in e.sessions)
        ]

    def get_team_schedule(self, team_id: str, league: str, days_ahead: int = 14) -> list[Event]:
        return []

    def get_team(self, team_id: str, league: str) -> Team | None:
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        self._ensure_loaded()
        for event in self._events_by_league.get(league, []):
            if event.id == event_id:
                return event
        return None

    # -------------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """(Re)load the schedule cache when stale, empty, or never loaded.

        Keeps previously-loaded data when a refresh yields nothing, so one
        failed fetch can't blank an already-working schedule.
        """
        now = datetime.now(UTC)
        if self._loaded_at is not None:
            age = (now - self._loaded_at).total_seconds()
            has_data = any(self._events_by_league.values())
            max_age = self._CACHE_TTL_SECONDS if has_data else self._EMPTY_RETRY_SECONDS
            if age < max_age:
                return

        loaded = self._load(now.year)
        if any(loaded.values()) or not any(self._events_by_league.values()):
            self._events_by_league = loaded
        self._loaded_at = now

    def _load(self, year: int) -> dict[str, list[Event]]:
        """Fetch and parse schedules for all NASCAR series."""
        # Cup has its own URL; ORAP and Trucks share a response.
        # Fetch each distinct URL once.
        fetched: dict[str, list | dict | None] = {}
        result: dict[str, list[Event]] = {}

        for league, (suffix, series_key) in _LEAGUE_CONFIG.items():
            url = f"{_BASE_URL}/{year}/{suffix}"
            if url not in fetched:
                fetched[url] = self._fetch(url)

            raw = fetched[url]
            if raw is None:
                logger.warning("[NASCAR] No data for %s (year=%d)", league, year)
                result[league] = []
                continue

            if series_key:
                raw_races = raw.get(series_key, []) if isinstance(raw, dict) else []
            else:
                raw_races = raw if isinstance(raw, list) else []

            events = []
            for race in raw_races:
                event = self._parse_race(race, league)
                if event:
                    events.append(event)
            events.sort(key=lambda e: e.start_time)
            result[league] = events

            logger.info("[NASCAR] Loaded %d races for %s (%d)", len(events), league, year)

        return result

    def _fetch(self, url: str) -> list | dict | None:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("[NASCAR] HTTP %d fetching %s", e.response.status_code, url)
        except Exception as e:
            logger.warning("[NASCAR] Failed to fetch %s: %s", url, e)
        return None

    def _parse_race(self, data: dict, league: str) -> Event | None:
        try:
            race_id = data.get("race_id")
            race_name = data.get("race_name", "")
            track_name = data.get("track_name", "")
            tv_broadcaster = data.get("television_broadcaster") or ""
            race_laps = data.get("scheduled_laps")
            race_distance = data.get("scheduled_distance")
            stage_laps_raw = [
                data.get("stage_1_laps") or 0,
                data.get("stage_2_laps") or 0,
                data.get("stage_3_laps") or 0,
            ]
            stage_laps = [x for x in stage_laps_raw if x > 0]
            if not race_id or not race_name:
                return None

            sessions = []
            for entry in data.get("schedule", []):
                run_type = entry.get("run_type", 0)
                if run_type not in (_RUN_PRACTICE, _RUN_QUALIFYING, _RUN_RACE):
                    continue
                start_str = entry.get("start_time_utc")
                if not start_str:
                    continue
                try:
                    # start_time_utc is UTC but lacks the Z suffix
                    start_time = datetime.fromisoformat(start_str).replace(tzinfo=UTC)
                except ValueError:
                    continue
                code, name = _session_code_and_name(entry.get("event_name", ""), run_type)
                sessions.append(RacingSession(code=code, name=name, start_time=start_time))

            if not sessions:
                return None

            sessions.sort(key=lambda s: s.start_time)

            venue = Venue(name=track_name) if track_name else None

            event_team = Team(
                id=f"nascar_event_{race_id}",
                provider=self.name,
                name=race_name,
                short_name=race_name[:20],
                abbreviation=_make_abbrev(race_name),
                league=league,
                sport="racing",
                logo_url=None,
                color=None,
            )

            return Event(
                id=str(race_id),
                provider=self.name,
                name=race_name,
                short_name=race_name,
                start_time=sessions[0].start_time,
                home_team=event_team,
                away_team=event_team,
                status=EventStatus(state="scheduled"),
                league=league,
                sport="racing",
                venue=venue,
                broadcasts=[tv_broadcaster] if tv_broadcaster else [],
                circuit_name=track_name or None,
                sessions=sessions,
                race_laps=int(race_laps) if race_laps is not None else None,
                race_distance_miles=float(race_distance) if race_distance is not None else None,
                stage_laps=stage_laps,
            )

        except Exception as e:
            logger.warning(
                "[NASCAR] Failed to parse race %r for %s: %s",
                data.get("race_id"), league, e,
            )
            return None
