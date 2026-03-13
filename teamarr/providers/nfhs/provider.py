from __future__ import annotations

import logging
import threading
from typing import List

from teamarr.core import (
    Event,
    EventStatus,
    SportsProvider,
    Team,
    Venue,
)

from teamarr.providers.nfhs.config import (
    GENDER_NORMALIZATION,
    LEAGUE_MAP,
    LEVEL_NORMALIZATION,
    SPORT_NORMALIZATION,
    STATE_FILTER,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_LEVELS,
    SUPPORTED_SPORTS,
    SUPPORTED_STATUSES,
)
from teamarr.providers.nfhs.client import NFHSClient

logger = logging.getLogger(__name__)


class NFHSProvider(SportsProvider):
    """
    NFHS Network provider (High School sports).

    Phase 1 scope:
      - Supported levels from config
      - Selected sports from config
      - Event discovery from upcoming + live endpoints
    """
    _shared_schools_by_state_cache: dict[str, list[dict]] = {}
    _shared_school_teams_cache: dict[str, list[dict]] = {}
    _shared_latest_team_rows_cache: dict[tuple[str, ...], list[dict]] = {}
    _shared_schools_lock = threading.RLock()
    _shared_school_teams_lock = threading.RLock()
    _shared_latest_team_rows_lock = threading.RLock()
    _shared_raw_team_row_count_cache: dict[tuple[str, ...], int] = {}

    name = "nfhs"

    def __init__(self) -> None:
        self.client = NFHSClient()

    # ------------------------------------------------------------------
    # Supported leagues
    # ------------------------------------------------------------------

    def get_supported_leagues(self) -> List[str]:
        """
        Return canonical leagues supported by this provider.
        """
        leagues = sorted(set(LEAGUE_MAP.values()))
        return leagues

    # ------------------------------------------------------------------
    # Team discovery
    # ------------------------------------------------------------------

    def get_league_teams(self, league_code: str) -> List[Team]:
        """
        Return teams belonging to a canonical league.
        """
        teams: List[Team] = []
        latest_team_rows = self._get_latest_team_rows()
        raw_team_row_count = self._get_raw_team_row_count()
        skipped_duplicate_teams = max(0, raw_team_row_count - len(latest_team_rows))

        for team in latest_team_rows:
            sport = SPORT_NORMALIZATION.get(team.get("sport"), team.get("sport"))
            gender = GENDER_NORMALIZATION.get(team.get("gender"), team.get("gender"))
            level = LEVEL_NORMALIZATION.get(team.get("level"), team.get("level"))

            if level not in SUPPORTED_LEVELS:
                continue

            if sport not in SUPPORTED_SPORTS:
                continue

            mapped = LEAGUE_MAP.get((sport, gender)) or LEAGUE_MAP.get((sport, None))

            if mapped != league_code:
                continue

            parsed_team = self._parse_team(team, league_code, sport)
            if parsed_team:
                teams.append(parsed_team)

        logger.info(
            "[NFHS] %s teams loaded for %s (state_filter=%s skipped_historical_team_rows=%s latest_team_rows=%s)",
            len(teams),
            league_code,
            sorted(STATE_FILTER) if STATE_FILTER else None,
            skipped_duplicate_teams,
            len(latest_team_rows),
        )
        return teams

    # ------------------------------------------------------------------
    # Event discovery
    # ------------------------------------------------------------------

    def get_events(self) -> List[Event]:
        """
        Fetch upcoming + live NFHS events.
        """
        events: List[Event] = []
        seen_events: set[str] = set()
        skipped_missing_id = 0
        skipped_duplicate = 0
        skipped_state = 0
        skipped_content_type = 0
        skipped_status = 0
        skipped_level = 0
        skipped_sport = 0
        skipped_unmapped_league = 0
        skipped_missing_teams = 0

        upcoming = self.client.get_upcoming_events() or []
        live = self.client.get_live_events() or []

        for event in upcoming + live:
            event_id = event.get("id") or event.get("key")
            if not event_id:
                skipped_missing_id += 1
                continue

            if event_id in seen_events:
                skipped_duplicate += 1
                continue

            seen_events.add(event_id)

            sport = SPORT_NORMALIZATION.get(event.get("sport"), event.get("sport"))
            gender = GENDER_NORMALIZATION.get(event.get("gender"), event.get("gender"))
            level = LEVEL_NORMALIZATION.get(event.get("level"), event.get("level"))
            content_type = event.get("content_type")
            status = event.get("status")
            state_code = event.get("state_code") or event.get("state")

            if STATE_FILTER and state_code not in STATE_FILTER:
                skipped_state += 1
                continue

            if content_type not in SUPPORTED_CONTENT_TYPES:
                skipped_content_type += 1
                continue

            if status not in SUPPORTED_STATUSES:
                skipped_status += 1
                continue

            if level not in SUPPORTED_LEVELS:
                skipped_level += 1
                continue

            if sport not in SUPPORTED_SPORTS:
                skipped_sport += 1
                continue

            league = LEAGUE_MAP.get((sport, gender)) or LEAGUE_MAP.get((sport, None))

            if not league:
                skipped_unmapped_league += 1
                continue

            teams = event.get("teams") or event.get("participants") or []

            if len(teams) < 2:
                skipped_missing_teams += 1
                continue

            parsed_event = self._parse_event(
                event=event,
                event_id=event_id,
                league=league,
                sport=sport,
                gender=gender,
                level=level,
                teams=teams,
                status=status,
            )
            if parsed_event:
                events.append(parsed_event)

        logger.info(
            "[NFHS] %s events discovered (skipped: missing_id=%s duplicate=%s state=%s content_type=%s status=%s level=%s sport=%s unmapped_league=%s missing_teams=%s)",
            len(events),
            skipped_missing_id,
            skipped_duplicate,
            skipped_state,
            skipped_content_type,
            skipped_status,
            skipped_level,
            skipped_sport,
            skipped_unmapped_league,
            skipped_missing_teams,
        )
        return events

    # ------------------------------------------------------------------
    # Required provider interface methods
    # ------------------------------------------------------------------

    def supports_league(self, league_code: str) -> bool:
        """Return whether this provider supports the given league."""
        return league_code in self.get_supported_leagues()

    def get_team(self, league_code: str, team_id: str) -> Team | None:
        """Return a single team by ID within a league."""
        for team in self.get_league_teams(league_code):
            if str(team.id) == str(team_id):
                return team
        return None

    def get_event(self, league_code: str, event_id: str) -> Event | None:
        """Return a single event by ID within a league."""
        if not self.supports_league(league_code):
            return None

        event_id_str = str(event_id)
        for event in self.get_events():
            if event.league != league_code:
                continue
            if str(event.id) == event_id_str:
                return event
        return None

    def get_team_schedule(self, league_code: str, team_id: str) -> List[Event]:
        """Return events for a specific team within a league."""
        schedule: List[Event] = []

        for event in self.get_events():
            if event.league != league_code:
                continue

            home_id = str(event.home_team.id) if event.home_team else None
            away_id = str(event.away_team.id) if event.away_team else None

            if str(team_id) in {home_id, away_id}:
                schedule.append(event)

        return schedule

    def _get_schools_for_state_cached(self, state_code: str) -> list[dict]:
        """Return cached schools for a state, shared across provider instances."""
        cls = type(self)
        with cls._shared_schools_lock:
            if state_code not in cls._shared_schools_by_state_cache:
                cls._shared_schools_by_state_cache[state_code] = self.client.get_schools_for_state(state_code) or []
            return cls._shared_schools_by_state_cache[state_code]

    def _get_school_teams_cached(self, school_key: str) -> list[dict]:
        """Return cached NFHS SEARCH v3 team rows for a school, shared across provider instances."""
        cls = type(self)
        with cls._shared_school_teams_lock:
            if school_key not in cls._shared_school_teams_cache:
                cls._shared_school_teams_cache[school_key] = self.client.get_school_teams(school_key) or []
            return cls._shared_school_teams_cache[school_key]

    # _get_school_details_cached method removed: raw team discovery now uses SEARCH v3 only.

    def _get_raw_team_rows(self) -> list[dict]:
        """Return raw NFHS SEARCH v3 team rows for the configured scope."""

        raw_team_rows: list[dict] = []

        if not STATE_FILTER:
            logger.warning("[NFHS] STATE_FILTER is empty; SEARCH v3 team discovery requires state-scoped school enumeration")
            return raw_team_rows

        for state_code in sorted(STATE_FILTER):
            schools = self._get_schools_for_state_cached(state_code)

            for school in schools:
                school_key = school.get("key")
                if not school_key:
                    continue

                latest_team_by_identity: dict[
                    tuple[str, str | None, str | None, str | None], dict
                ] = {}

                for team_row in self._get_school_teams_cached(school_key):
                    sport = SPORT_NORMALIZATION.get(team_row.get("sport"), team_row.get("sport"))
                    gender = GENDER_NORMALIZATION.get(team_row.get("gender"), team_row.get("gender"))
                    level = LEVEL_NORMALIZATION.get(team_row.get("level"), team_row.get("level"))

                    dedupe_key = (school_key, sport, gender, level)
                    updated_at = team_row.get("updated_at") or ""

                    existing = latest_team_by_identity.get(dedupe_key)
                    if existing is not None:
                        existing_updated_at = existing.get("updated_at") or ""
                        if updated_at <= existing_updated_at:
                            continue

                    resolved_row = dict(team_row)
                    resolved_row["_resolved_school_key"] = school_key
                    resolved_row["_resolved_school_name"] = (
                        school.get("name")
                        or school.get("short_name")
                        or school.get("slug")
                    )
                    resolved_row["_resolved_school_short_name"] = (
                        school.get("short_name")
                        or school.get("name")
                        or school.get("slug")
                    )
                    resolved_row["_resolved_school_logo"] = school.get("logo")
                    resolved_row["_resolved_school_acronym"] = school.get("acronym")
                    resolved_row["sport"] = sport
                    resolved_row["gender"] = gender
                    resolved_row["level"] = level

                    # SEARCH v3 returns colors we do not use downstream.
                    resolved_row.pop("primary_color", None)
                    resolved_row.pop("secondary_color", None)

                    latest_team_by_identity[dedupe_key] = resolved_row

                raw_team_rows.extend(latest_team_by_identity.values())

        return raw_team_rows

    def _get_raw_team_row_count(self) -> int:
        """Return the total number of raw NFHS SEARCH v3 team rows before deduplication."""
        scope_key = tuple(sorted(STATE_FILTER)) if STATE_FILTER else ("ALL",)
        cls = type(self)
        with cls._shared_latest_team_rows_lock:
            if scope_key not in cls._shared_raw_team_row_count_cache:
                cls._shared_raw_team_row_count_cache[scope_key] = len(self._get_raw_team_rows())
            return cls._shared_raw_team_row_count_cache[scope_key]

    def _get_latest_team_rows(self) -> list[dict]:
        """
        Return deduplicated NFHS team rows, cached across provider instances by filter scope.
        Source data now comes from the SEARCH API and may contain multiple rows per sport/gender/level.
        """
        scope_key = tuple(sorted(STATE_FILTER)) if STATE_FILTER else ("ALL",)
        cls = type(self)
        with cls._shared_latest_team_rows_lock:
            if scope_key in cls._shared_latest_team_rows_cache:
                return cls._shared_latest_team_rows_cache[scope_key]

            latest_team_rows: dict[tuple[str | None, str | None, str | None, str | None], dict] = {}
            raw_team_rows = self._get_raw_team_rows()

            for team in raw_team_rows:
                sport = SPORT_NORMALIZATION.get(team.get("sport"), team.get("sport"))
                gender = GENDER_NORMALIZATION.get(team.get("gender"), team.get("gender"))
                level = LEVEL_NORMALIZATION.get(team.get("level"), team.get("level"))
                school_key = team.get("_resolved_school_key") or team.get("school_key")
                dedupe_key = (school_key, sport, gender, level)
                updated_at = team.get("updated_at") or ""

                existing = latest_team_rows.get(dedupe_key)
                if existing is not None:
                    existing_updated_at = existing.get("updated_at") or ""
                    if updated_at <= existing_updated_at:
                        continue

                latest_team_rows[dedupe_key] = team

            cls._shared_latest_team_rows_cache[scope_key] = list(latest_team_rows.values())
            cls._shared_raw_team_row_count_cache[scope_key] = len(raw_team_rows)
            logger.info(
                "[NFHS] Cached %s latest team rows from %s raw team rows (state_filter=%s)",
                len(cls._shared_latest_team_rows_cache[scope_key]),
                len(raw_team_rows),
                sorted(STATE_FILTER) if STATE_FILTER else None,
            )
            return cls._shared_latest_team_rows_cache[scope_key]

    def _parse_team(self, team_data: dict, league: str, sport: str) -> Team | None:
        school_key = team_data.get("_resolved_school_key") or team_data.get("school_key")
        if not school_key:
            return None

        gender = GENDER_NORMALIZATION.get(team_data.get("gender"), team_data.get("gender"))
        level = LEVEL_NORMALIZATION.get(team_data.get("level"), team_data.get("level"))
        team_id = f"{school_key}:{sport or 'unknown'}:{gender or 'unknown'}:{level or 'unknown'}"

        school_name = (
            team_data.get("_resolved_school_name")
            or team_data.get("school", {}).get("name")
            or team_data.get("name")
            or team_data.get("short_name")
        )
        school_short_name = (
            team_data.get("_resolved_school_short_name")
            or team_data.get("school", {}).get("short_name")
            or team_data.get("short_name")
            or school_name
        )

        name = school_name or f"{sport or 'Unknown'} Team"
        short_name = school_short_name or name
        abbreviation = (
            team_data.get("_resolved_school_acronym")
            or team_data.get("acronym")
            or short_name[:3].upper()
        )
        logo_url = (
            team_data.get("logo")
            or team_data.get("_resolved_school_logo")
            or team_data.get("school", {}).get("logo")
        )

        return Team(
            id=str(team_id),
            provider=self.name,
            name=name,
            short_name=short_name,
            abbreviation=abbreviation,
            league=league,
            sport=sport,
            logo_url=logo_url,
        )

    def _parse_status(self, raw_status: str | None) -> EventStatus:
        normalized = (raw_status or "scheduled").lower()

        if normalized in {"live", "in_progress", "in progress"}:
            state = "in_progress"
        elif normalized in {"final", "completed", "complete", "ended"}:
            state = "final"
        elif normalized in {"postponed"}:
            state = "postponed"
        elif normalized in {"cancelled", "canceled"}:
            state = "cancelled"
        else:
            state = "scheduled"

        return EventStatus(state=state, detail=raw_status or state)

    def _parse_venue(self, event_data: dict) -> Venue | None:
        venue_name = None
        city = event_data.get("city")
        state = event_data.get("state_code") or event_data.get("state")

        publishers = event_data.get("publishers") or []
        if publishers:
            venue_name = publishers[0].get("name") or publishers[0].get("formatted_name")

        if not venue_name and not city and not state:
            return None

        return Venue(
            name=venue_name or "NFHS Venue",
            city=city,
            state=state,
        )

    def _parse_event(
        self,
        *,
        event: dict,
        event_id: str,
        league: str,
        sport: str,
        gender: str | None,
        level: str | None,
        teams: list[dict],
        status: str | None,
    ) -> Event | None:
        if len(teams) < 2:
            return None

        home_team_key = event.get("home_team") or event.get("home_participant")

        team1 = teams[0]
        team2 = teams[1]

        def _participant_school_key(t: dict) -> str | None:
            return t.get("school_key") or t.get("_resolved_school_key") or t.get("key")

        team1_school = _participant_school_key(team1)
        team2_school = _participant_school_key(team2)

        if home_team_key and team1_school == home_team_key and team2_school != home_team_key:
            team1, team2 = team2, team1

        away_team = self._parse_team(team1, league, sport)
        home_team = self._parse_team(team2, league, sport)

        if not home_team or not away_team:
            return None

        short_name = event.get("title") or f"{away_team.short_name} vs {home_team.short_name}"
        name = event.get("subheadline") or f"{away_team.name} vs. {home_team.name}"
        if gender and level:
            name = f"{name} ({level} {gender})"

        return Event(
            id=event_id,
            provider=self.name,
            name=name,
            short_name=short_name,
            start_time=event.get("start_time"),
            home_team=home_team,
            away_team=away_team,
            status=self._parse_status(status),
            league=league,
            sport=sport,
            venue=self._parse_venue(event),
        )

    def close(self) -> None:
        """Close underlying client resources."""
        self.client.close()