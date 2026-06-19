"""Tournament event parsing for ESPN provider.

Handles sports like tennis, golf, and racing that don't have
traditional home/away matchups.
"""

import logging
from datetime import date, datetime

from teamarr.core import Event, EventStatus, RacingResult, RacingSession, Team, Venue

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
    "sq": "sprint_qualifying",
    "sprint qualifying": "sprint_qualifying",
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
