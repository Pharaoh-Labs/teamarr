from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import List
from teamarr.database.connection import get_connection
from teamarr.database.settings.read import get_nfhs_settings

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
      - Event discovery from SEARCH upcoming events per school
    """
    _shared_schools_by_state_cache: dict[str, list[dict]] = {}
    _shared_school_teams_cache: dict[str, list[dict]] = {}
    _shared_school_upcoming_events_cache: dict[str, list[dict]] = {}
    _shared_upcoming_events_by_scope_cache: dict[tuple[str, ...], list[dict]] = {}
    _shared_latest_team_rows_cache: dict[tuple[str, ...], list[dict]] = {}
    _shared_schools_lock = threading.RLock()
    _shared_school_teams_lock = threading.RLock()
    _shared_school_upcoming_events_lock = threading.RLock()
    _shared_upcoming_events_by_scope_lock = threading.RLock()
    _shared_latest_team_rows_lock = threading.RLock()
    _shared_raw_team_row_count_cache: dict[tuple[str, ...], int] = {}

    name = "nfhs"

    def __init__(self) -> None:
        self.client = NFHSClient()

    def _get_runtime_state_filter(self) -> set[str]:
        """Return enabled NFHS state codes from persisted settings, or an empty set on read failure."""
        try:
            with get_connection() as conn:
                settings = get_nfhs_settings(conn)
                if not settings.enabled:
                    return set()
                return {
                    code.strip().upper()
                    for code in settings.state_codes
                    if isinstance(code, str) and code.strip()
                }
        except Exception as exc:
            logger.warning("[NFHS] Failed to load NFHS settings from database; disabling NFHS provider: %s", exc)
            return set()

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
        state_filter = self._get_runtime_state_filter()
        if not state_filter:
            logger.info("[NFHS] Provider disabled (no state codes configured); skipping team discovery")
            return []
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
            sorted(state_filter) if state_filter else None,
            skipped_duplicate_teams,
            len(latest_team_rows),
        )
        return teams

    # ------------------------------------------------------------------
    # Event discovery
    # ------------------------------------------------------------------

    def _resolve_known_team_for_event_participant(self, participant: dict, league: str, sport: str) -> Team | None:
        """Resolve an event participant to a known cached NFHS team without creating new opponent teams."""
        participant_school_key = (
            participant.get("school_key")
            or participant.get("_resolved_school_key")
            or participant.get("key")
        )
        if not participant_school_key:
            return None

        participant_gender_raw = participant.get("gender")
        participant_level_raw = participant.get("level")
        participant_sport_raw = participant.get("sport")

        participant_gender = GENDER_NORMALIZATION.get(participant_gender_raw, participant_gender_raw)
        participant_level = LEVEL_NORMALIZATION.get(participant_level_raw, participant_level_raw)
        participant_sport = SPORT_NORMALIZATION.get(participant_sport_raw, participant_sport_raw)

        for team_row in self._get_latest_team_rows():
            school_key = team_row.get("_resolved_school_key") or team_row.get("school_key")
            row_sport = SPORT_NORMALIZATION.get(team_row.get("sport"), team_row.get("sport"))
            row_gender = GENDER_NORMALIZATION.get(team_row.get("gender"), team_row.get("gender"))
            row_level = LEVEL_NORMALIZATION.get(team_row.get("level"), team_row.get("level"))

            sport_matches = row_sport == sport or row_sport == participant_sport
            gender_matches = participant_gender is None or row_gender == participant_gender
            level_matches = participant_level is None or row_level == participant_level

            if (
                school_key == participant_school_key
                and sport_matches
                and gender_matches
                and level_matches
            ):
                return self._parse_team(team_row, league, sport)

        return None

    def get_events(self, league: str | None = None, target_date=None) -> List[Event]:
        """Fetch NFHS SEARCH upcoming events per school for an optional league and date."""
        state_filter = self._get_runtime_state_filter()
        if not state_filter:
            logger.info("[NFHS] Provider disabled (no state codes configured); skipping event discovery")
            return []
        target_date_str = None
        if target_date is not None:
            try:
                target_date_str = target_date.isoformat()
            except AttributeError:
                target_date_str = str(target_date)
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

        upcoming = self._get_upcoming_events_for_scope_cached(state_filter)

        for event in upcoming:
            event_id = event.get("id") or event.get("key")
            if not event_id:
                skipped_missing_id += 1
                continue

            if event_id in seen_events:
                skipped_duplicate += 1
                continue
            local_start_time = event.get("local_start_time") or event.get("start_time") or ""
            if target_date_str and not str(local_start_time).startswith(target_date_str):
                continue
            seen_events.add(event_id)

            sport_raw = event.get("sport")
            gender_raw = event.get("gender")
            level_raw = event.get("level")

            teams = event.get("participants") or event.get("teams") or []
            if teams:
                if not gender_raw:
                    gender_raw = teams[0].get("gender")
                if not level_raw:
                    level_raw = teams[0].get("level")
                if not sport_raw:
                    sport_raw = teams[0].get("sport")

            sport = SPORT_NORMALIZATION.get(sport_raw, sport_raw)
            gender = GENDER_NORMALIZATION.get(gender_raw, gender_raw)
            level = LEVEL_NORMALIZATION.get(level_raw, level_raw)
            content_type = event.get("content_type")
            status = event.get("status")
            state_code = event.get("state_code") or event.get("state")
            if not content_type:
                content_type = "game"

            if state_filter and state_code not in state_filter:
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

            league_code = LEAGUE_MAP.get((sport, gender)) or LEAGUE_MAP.get((sport, None))

            if not league_code:
                skipped_unmapped_league += 1
                continue

            if league and league_code != league:
                continue

            if len(teams) < 2:
                skipped_missing_teams += 1
                continue

            parsed_event = self._parse_event(
                event=event,
                event_id=event_id,
                league=league_code,
                sport=sport,
                gender=gender,
                level=level,
                teams=teams,
                status=status,
            )
            if parsed_event:
                events.append(parsed_event)

        logger.info(
            "[NFHS] %s events discovered from SEARCH upcoming per-school fetch (skipped: missing_id=%s duplicate=%s state=%s content_type=%s status=%s level=%s sport=%s unmapped_league=%s missing_teams=%s)",
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
        for event in self.get_events(league_code):
            if str(event.id) == event_id_str:
                return event
        return None

    def get_team_schedule(self, league_code: str, team_id: str) -> List[Event]:
        """Return events for a specific team within a league."""
        schedule: List[Event] = []

        for event in self.get_events(league_code):
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

    def _get_school_upcoming_events_cached(self, school_key: str) -> list[dict]:
        """Return cached NFHS SEARCH v3 upcoming event rows for a school, shared across provider instances."""
        cls = type(self)
        with cls._shared_school_upcoming_events_lock:
            if school_key not in cls._shared_school_upcoming_events_cache:
                cls._shared_school_upcoming_events_cache[school_key] = self.client.get_upcoming_events_for_school(
                    school_key) or []
            return cls._shared_school_upcoming_events_cache[school_key]

    def _get_upcoming_events_for_scope_cached(self, state_filter: set[str]) -> list[dict]:
        """Return cached aggregated upcoming NFHS events for the configured state scope."""
        scope_key = tuple(sorted(state_filter)) if state_filter else ("ALL",)
        cls = type(self)

        with cls._shared_upcoming_events_by_scope_lock:
            if scope_key in cls._shared_upcoming_events_by_scope_cache:
                return cls._shared_upcoming_events_by_scope_cache[scope_key]

            upcoming: list[dict] = []
            for state_code in sorted(state_filter):
                schools = self._get_schools_for_state_cached(state_code)
                for school in schools:
                    school_key = school.get("key")
                    if not school_key:
                        continue
                    upcoming.extend(self._get_school_upcoming_events_cached(school_key))

            cls._shared_upcoming_events_by_scope_cache[scope_key] = upcoming
            return upcoming

    def _get_raw_team_rows(self) -> list[dict]:
        """Return raw NFHS SEARCH v3 team rows for the configured scope."""

        state_filter = self._get_runtime_state_filter()
        raw_team_rows: list[dict] = []

        if not state_filter:
            logger.warning("[NFHS] NFHS is enabled but no state codes are configured; skipping team discovery")
            return raw_team_rows

        for state_code in sorted(state_filter):
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
        state_filter = self._get_runtime_state_filter()
        scope_key = tuple(sorted(state_filter)) if state_filter else ("ALL",)
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
        state_filter = self._get_runtime_state_filter()
        scope_key = tuple(sorted(state_filter)) if state_filter else ("ALL",)
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
                sorted(state_filter) if state_filter else None,
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
            team_data.get("_resolved_school_logo")
            or team_data.get("logo")
            or team_data.get("school", {}).get("logo")
        )

        canonical_sport = self._canonical_sport_code(sport)

        return Team(
            id=str(team_id),
            provider=self.name,
            name=name,
            short_name=short_name,
            abbreviation=abbreviation,
            league=league,
            sport=canonical_sport,
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

    def _participant_display_name(self, participant: dict) -> str:
        """Return a safe display name for an event participant without creating a Team."""
        candidates = [
            participant.get("name"),
            participant.get("short_name"),
            participant.get("acronym"),
        ]

        for value in candidates:
            if not value:
                continue
            normalized = str(value).strip()
            if normalized.lower() not in {"away", "home", "tbd"}:
                return normalized

        return (
            participant.get("name")
            or participant.get("short_name")
            or participant.get("acronym")
            or "TBD"
        )

    def _build_event_only_team(self, participant: dict, league: str, sport: str) -> Team:
        """Build a lightweight event-only Team for unresolved NFHS opponents."""
        school_key = (
            participant.get("school_key")
            or participant.get("_resolved_school_key")
            or participant.get("key")
            or participant.get("slug")
            or self._participant_display_name(participant)
        )

        name = (
            participant.get("name")
            or participant.get("short_name")
            or participant.get("acronym")
            or "Unknown Team"
        )
        if str(name).strip().lower() in {"away", "home", "tbd"}:
            name = self._participant_display_name(participant)
        short_name = (
            participant.get("short_name")
            or participant.get("acronym")
            or name
        )
        if str(short_name).strip().lower() in {"away", "home", "tbd"}:
            short_name = name
        abbreviation = (
            participant.get("acronym")
            or short_name[:3].upper()
        )
        logo_url = participant.get("logo")

        canonical_sport = self._canonical_sport_code(sport)

        return Team(
            id=f"nfhs-event-only:{school_key}:{league}:{canonical_sport}",
            provider=self.name,
            name=name,
            short_name=short_name,
            abbreviation=abbreviation,
            league=league,
            sport=canonical_sport,
            logo_url=logo_url,
        )

    def _canonical_sport_code(self, sport: str | None) -> str:
        """Map NFHS sport labels to Teamarr canonical sport codes."""
        if not sport:
            return "sports"

        mapping = {
            "Baseball": "baseball",
            "Basketball": "basketball",
            "Bowling": "bowling",
            "Cheer": "cheer",
            "Cross Country": "cross-country",
            "Field Hockey": "field-hockey",
            "Flag Football": "flag-football",
            "Football": "football",
            "Golf": "golf",
            "Gymnastics": "gymnastics",
            "Ice Hockey": "hockey",
            "Lacrosse": "lacrosse",
            "Soccer": "soccer",
            "Softball": "softball",
            "Swimming": "swimming",
            "Tennis": "tennis",
            "Track & Field": "track-and-field",
            "Volleyball": "volleyball",
            "Water Polo": "water-polo",
            "Wrestling": "wrestling",
            # Lowercase/alternate forms
            "baseball": "baseball",
            "basketball": "basketball",
            "bowling": "bowling",
            "cheer": "cheer",
            "cross country": "cross-country",
            "field hockey": "field-hockey",
            "flag football": "flag-football",
            "football": "football",
            "golf": "golf",
            "gymnastics": "gymnastics",
            "ice hockey": "hockey",
            "hockey": "hockey",
            "lacrosse": "lacrosse",
            "soccer": "soccer",
            "softball": "softball",
            "swimming": "swimming",
            "tennis": "tennis",
            "track & field": "track-and-field",
            "track and field": "track-and-field",
            "volleyball": "volleyball",
            "water polo": "water-polo",
            "wrestling": "wrestling",
            # Already-canonical Teamarr sport codes
            "cross-country": "cross-country",
            "field-hockey": "field-hockey",
            "flag-football": "flag-football",
            "track-and-field": "track-and-field",
            "water-polo": "water-polo",
        }
        return mapping.get(str(sport).strip(), mapping.get(str(sport).strip().lower(), "sports"))

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

        away_team = self._resolve_known_team_for_event_participant(team1, league, sport)
        home_team = self._resolve_known_team_for_event_participant(team2, league, sport)

        # Keep events only if at least one side resolves to a known NFHS team.
        if not home_team and not away_team:
            return None

        # Build lightweight event-only teams for unresolved opponents so caching
        # and downstream display logic always have both sides populated.
        if not away_team:
            away_team = self._build_event_only_team(team1, league, sport)
        if not home_team:
            home_team = self._build_event_only_team(team2, league, sport)

        away_name = away_team.short_name
        home_name = home_team.short_name
        away_full_name = away_team.name
        home_full_name = home_team.name

        short_name = event.get("title") or f"{away_name} vs {home_name}"
        name = event.get("subheadline") or f"{away_full_name} vs. {home_full_name}"
        if gender and level:
            name = f"{name} ({level} {gender})"

        start_time_raw = event.get("local_start_time") or event.get("start_time")
        start_time = None
        if start_time_raw:
            try:
                start_time = datetime.fromisoformat(str(start_time_raw).replace("Z", "+00:00"))
            except ValueError:
                return None

        canonical_sport = self._canonical_sport_code(sport)

        return Event(
            id=event_id,
            provider=self.name,
            name=name,
            short_name=short_name,
            start_time=start_time,
            home_team=home_team,
            away_team=away_team,
            status=self._parse_status(status),
            league=league,
            sport=canonical_sport,
            venue=self._parse_venue(event),
        )

    def close(self) -> None:
        """Close underlying client resources."""
        self.client.close()