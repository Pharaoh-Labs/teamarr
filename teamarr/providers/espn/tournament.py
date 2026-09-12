"""Tournament event parsing for ESPN provider.

Handles sports like tennis, golf, and racing that don't have
traditional home/away matchups.
"""

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from unidecode import unidecode

from teamarr.core import Event, EventStatus, RacingResult, RacingSession, Team, Venue
from teamarr.database.race_feeds import RosterEntry

if TYPE_CHECKING:
    from teamarr.providers.espn.client import ESPNClient

logger = logging.getLogger(__name__)

# ESPN session type abbreviations -> our canonical session codes.
# Untyped single-competition events (e.g. NASCAR scoreboard, which returns
# one competition with no "type") fall back to "race".
_RACING_SESSION_ABBREV_MAP = {
    "fp1": "fp1",
    "fp2": "fp2",
    "fp3": "fp3",
    "p1": "fp1",
    "p2": "fp2",
    "p3": "fp3",
    "ss": "sprint_qualifying",
    "sq": "sprint_qualifying",
    "sprint qualifying": "sprint_qualifying",
    "sprint shootout": "sprint_qualifying",
    "sr": "sprint",
    "sprint race": "sprint",
    "sprint": "sprint",
    "qual": "qualifying",
    "qualifying": "qualifying",
    "race": "race",
}

_RACING_SESSION_NAMES = {
    "fp1": "Practice 1",
    "fp2": "Practice 2",
    "fp3": "Practice 3",
    "sprint_qualifying": "Sprint Qualifying",
    "sprint": "Sprint",
    "qualifying": "Qualifying",
    "race": "Race",
}


# FIA-style three-letter driver codes. ESPN gives no abbreviation for drivers;
# the first three letters of the surname cover the whole current grid
# (VER/HAM/LEC/NOR/PIA/RUS/SAI/ALO/ANT/TSU/...). The override map exists for
# the collisions the FIA itself resolves by hand (Schumacher = MSC, not SCH).
_DRIVER_CODE_OVERRIDES: dict[str, str] = {
    "schumacher": "MSC",
}


def _driver_code(full_name: str) -> str | None:
    parts = unidecode(full_name).replace(".", "").split()
    if len(parts) < 2:
        return None
    surname = parts[-1] if parts[-1].lower() not in {"jr", "sr", "ii", "iii"} else parts[-2]
    key = surname.lower()
    if key in _DRIVER_CODE_OVERRIDES:
        return _DRIVER_CODE_OVERRIDES[key]
    letters = "".join(ch for ch in surname if ch.isalpha())
    return letters[:3].upper() if len(letters) >= 3 else None


def _racing_session_info(type_data: dict | None) -> tuple[str, str]:
    """Map an ESPN competition `type` block to (session_code, session_name)."""
    abbrev = (type_data or {}).get("abbreviation", "").strip().lower()
    code = _RACING_SESSION_ABBREV_MAP.get(abbrev, "race")
    name = _RACING_SESSION_NAMES.get(code, code.replace("_", " ").title())
    return code, name


class TournamentParserMixin:
    """Mixin providing tournament-specific parsing methods.

    Requires:
        - self._client: ESPNClient instance
        - self.name: Provider name ('espn')
    """

    if TYPE_CHECKING:
        # Provided by the host provider class (ESPNProvider).
        _client: "ESPNClient"
        name: str

        def _get_sport_league_from_db(self, league: str) -> tuple[str, str] | None: ...

        def _parse_tennis_matches(
            self, data: dict, league: str, sport: str, target_date: date
        ) -> list[Event]: ...

    def _get_tournament_events(
        self,
        league: str,
        target_date: date,
        sport: str,
        sport_league: tuple[str, str] | None = None,
    ) -> list[Event]:
        """Get events for tournament sports (tennis, golf, racing).

        These sports have tournaments/races as events with many competitors,
        not head-to-head matchups with home/away.
        """
        date_str = target_date.strftime("%Y%m%d")
        data = self._client.get_scoreboard(league, date_str, sport_league)
        if not data:
            return []

        events = []
        for event_data in data.get("events", []):
            if sport == "racing":
                event = self._parse_racing_event(event_data, league, sport)
            elif sport == "tennis":
                # Tennis expands to one Event per match (TennisParserMixin),
                # not one placeholder Event per tournament
                events.extend(
                    self._parse_tennis_matches(event_data, league, sport, target_date)
                )
                continue
            else:
                event = self._parse_tournament_event(event_data, league, sport)
            if event:
                events.append(event)

        return events

    def _parse_tournament_event(self, data: dict, league: str, sport: str) -> Event | None:
        """Parse a tournament-style event (tennis, golf, racing).

        Creates placeholder 'teams' representing the tournament/event itself.
        """
        try:
            event_id = data.get("id", "")
            if not event_id:
                return None

            # Parse start time
            date_str = data.get("date")
            if not date_str:
                return None

            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            event_name = data.get("name", "")
            short_name = data.get("shortName", event_name)

            # For tournaments, create placeholder "teams"
            # This allows the event to work with existing matching logic
            tournament_team = Team(
                id=f"tournament_{event_id}",
                provider=self.name,
                name=event_name,
                short_name=short_name[:20] if short_name else "",
                abbreviation=self._make_tournament_abbrev(event_name),
                league=league,
                sport=sport,
                logo_url=None,
                color=None,
            )

            # Parse status
            status_data = data.get("status", {})
            type_data = status_data.get("type", {}) if status_data else {}
            state = type_data.get("state", "pre")

            if state == "in":
                status = EventStatus(state="live", detail=type_data.get("detail"))
            elif state == "post":
                status = EventStatus(state="final", detail=type_data.get("detail"))
            else:
                status = EventStatus(state="scheduled")

            # Parse venue if available
            venue = None
            competitions = data.get("competitions", [])
            if competitions:
                venue_data = competitions[0].get("venue")
                if venue_data:
                    venue = Venue(
                        name=venue_data.get("fullName", ""),
                        city=venue_data.get("address", {}).get("city", ""),
                        state=venue_data.get("address", {}).get("state", ""),
                        country=venue_data.get("address", {}).get("country", ""),
                    )

            return Event(
                id=str(event_id),
                provider=self.name,
                name=event_name,
                short_name=short_name,
                start_time=start_time,
                home_team=tournament_team,
                away_team=tournament_team,  # Same team for tournaments
                status=status,
                league=league,
                sport=sport,
                venue=venue,
                broadcasts=[],
            )

        except Exception as e:
            logger.warning("[ESPN_TOURNAMENT] Failed to parse event: %s", e)
            return None

    def _parse_racing_event(self, data: dict, league: str, sport: str) -> Event | None:
        """Parse a racing event (Grand Prix, race weekend) into an Event.

        A racing event has one or more "sessions" (Practice/Qualifying/Race),
        each with its own start time and an ordered list of drivers
        (`RacingResult`). Like `_parse_tournament_event`, a placeholder
        "team" represents the event itself for the matching layer.
        """
        try:
            event_id = data.get("id", "")
            if not event_id:
                return None

            date_str = data.get("date")
            if not date_str:
                return None

            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            event_name = data.get("name", "")
            short_name = data.get("shortName", event_name)

            racing_team = Team(
                id=f"event_{event_id}",
                provider=self.name,
                name=event_name,
                short_name=short_name[:20] if short_name else "",
                abbreviation=self._make_tournament_abbrev(event_name),
                league=league,
                sport=sport,
                logo_url=None,
                color=None,
            )

            # ESPN's top-level event status mirrors the most recently
            # started/finished session, not the whole weekend - e.g. it
            # reports "Final" once Friday practice ends even though the
            # Race is still days away. Derive status from the *last*
            # session (the Race) so the event isn't considered final
            # until the weekend is actually over.
            competitions = data.get("competitions", [])
            last_competition = (
                max(competitions, key=lambda c: c.get("date", "")) if competitions else None
            )
            status_data = (last_competition or {}).get("status") or data.get("status", {})
            type_data = status_data.get("type", {}) if status_data else {}
            state = type_data.get("state", "pre")

            if state == "in":
                status = EventStatus(state="live", detail=type_data.get("detail"))
            elif state == "post":
                status = EventStatus(state="final", detail=type_data.get("detail"))
            else:
                status = EventStatus(state="scheduled")

            circuit_data = data.get("circuit") or {}
            circuit_name = circuit_data.get("fullName")
            venue = None
            if circuit_name:
                address = circuit_data.get("address") or {}
                venue = Venue(
                    name=circuit_name,
                    city=address.get("city"),
                    state=address.get("state"),
                    country=address.get("country"),
                )

            sessions = []
            for competition in competitions:
                session = self._parse_racing_session(competition)
                if session:
                    sessions.append(session)
            sessions.sort(key=lambda s: s.start_time)

            return Event(
                id=str(event_id),
                provider=self.name,
                name=event_name,
                short_name=short_name,
                start_time=start_time,
                home_team=racing_team,
                away_team=racing_team,  # Same placeholder team for racing events
                status=status,
                league=league,
                sport=sport,
                venue=venue,
                broadcasts=[],
                circuit_name=circuit_name,
                sessions=sessions,
            )

        except Exception as e:
            logger.warning("[ESPN_RACING] Failed to parse event: %s", e)
            return None

    # Leagues whose provider payload carries a usable driver roster (#245).
    # ESPN lists competitors ONLY on sessions that have run (a scheduled race
    # has zero), so the roster is harvested from the most recent COMPLETED
    # event of the season. F1 only: NASCAR (~40 cars, part-timers) and IndyCar
    # have no stable grid to speak of.
    ROSTER_LEAGUES: frozenset[str] = frozenset({"f1"})

    def get_race_roster(self, league: str) -> list[RosterEntry]:
        """The current driver grid for a roster league, from the last completed race.

        One scoreboard request for the whole season (``dates=YYYY0101-YYYY1231``,
        verified 2026-09-12: 25 events, the last completed race carrying 22
        competitors with fullName/displayName/shortName and a country flag, no
        ids and no constructor). Falls back to the previous season before the
        first race of a year. Empty when the league is not roster-capable or
        nothing has completed yet.
        """
        if league not in self.ROSTER_LEAGUES:
            return []
        sport_league = self._get_sport_league_from_db(league)
        year = date.today().year
        for season in (year, year - 1):
            data = self._client.get_scoreboard(league, f"{season}0101-{season}1231", sport_league)
            if not data:
                continue
            completed = [
                e for e in data.get("events", []) if self._last_session_state(e) == "post"
            ]
            if not completed:
                continue
            latest = max(completed, key=lambda e: e.get("date", ""))
            race = max(latest.get("competitions", []), key=lambda c: c.get("date", ""))
            roster = self._roster_from_competition(race)
            if roster:
                logger.info(
                    "[ESPN_RACING] %s roster: %d drivers from %s",
                    league,
                    len(roster),
                    latest.get("name"),
                )
                return roster
        return []

    @staticmethod
    def _last_session_state(event_data: dict) -> str:
        competitions = event_data.get("competitions", [])
        if not competitions:
            return "pre"
        last = max(competitions, key=lambda c: c.get("date", ""))
        return last.get("status", {}).get("type", {}).get("state", "pre")

    @staticmethod
    def _roster_from_competition(competition: dict) -> list[RosterEntry]:
        roster: list[RosterEntry] = []
        seen: set[str] = set()
        for competitor in competition.get("competitors", []):
            athlete = competitor.get("athlete") or {}
            name = athlete.get("fullName") or athlete.get("displayName")
            if not name or name in seen:
                continue
            seen.add(name)
            flag = (athlete.get("flag") or {}).get("href")
            roster.append(
                RosterEntry(
                    name=name,
                    short_name=athlete.get("shortName"),
                    code=_driver_code(name),
                    logo_url=flag,
                )
            )
        return roster

    def _parse_racing_session(self, competition: dict) -> "RacingSession | None":
        """Parse a single ESPN `competitions[]` entry into a RacingSession.

        Each entry represents one race-weekend session (Practice, Qualifying,
        Race, ...) with its own start time and ordered driver list.
        """
        date_str = competition.get("date")
        if not date_str:
            return None

        try:
            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None

        code, name = _racing_session_info(competition.get("type"))
        comp_state = competition.get("status", {}).get("type", {}).get("state", "pre")

        results = []
        for competitor in competition.get("competitors", []):
            athlete = competitor.get("athlete") or {}
            driver_name = athlete.get("fullName") or athlete.get("displayName")
            if not driver_name:
                continue

            order = competitor.get("order")
            results.append(
                RacingResult(
                    driver_name=driver_name,
                    position=order if comp_state == "post" else None,
                    grid_position=order if comp_state != "post" else None,
                    points=self._extract_points_stat(competitor.get("statistics", [])),
                    fastest_lap=self._has_fastest_lap_stat(competitor.get("statistics", [])),
                    status="Finished" if comp_state == "post" else None,
                )
            )

        return RacingSession(code=code, name=name, start_time=start_time, results=results)

    def _has_fastest_lap_stat(self, statistics: list) -> bool:
        """Check ESPN per-competitor `statistics` for a fastest-lap flag."""
        for stat in statistics or []:
            name = (stat.get("name") or "").lower()
            if "fastestlap" in name:
                return bool(stat.get("value"))
        return False

    def _extract_points_stat(self, statistics: list) -> float | None:
        """Extract championship points from ESPN per-competitor `statistics`."""
        for stat in statistics or []:
            name = (stat.get("name") or "").lower()
            if "points" in name:
                try:
                    return float(stat.get("value"))
                except (TypeError, ValueError):
                    return None
        return None

    def _make_tournament_abbrev(self, name: str) -> str:
        """Make abbreviation for tournament name."""
        # Take first letters of significant words
        words = [w for w in name.split() if len(w) > 2]
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words[:4])
        return name[:6].upper()
