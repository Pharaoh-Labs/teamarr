"""Tournament event parsing for ESPN provider.

Handles sports like tennis, golf, and racing that don't have
traditional home/away matchups.
"""

import logging
from datetime import date, datetime

from teamarr.config import get_user_timezone
from teamarr.core import Event, EventStatus, Team, Venue
from teamarr.utilities.tz import to_user_tz

logger = logging.getLogger(__name__)


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
        from teamarr.utilities.tz import to_user_tz

        for event_data in data.get("events", []):
            # For tournament sports, an "event" (like a Grand Prix) can contain
            # multiple "competitions" (Practice 1, Practice 2, Qualifying, Race).
            # We want each competition to be its own Event in Teamarr.
            competitions = event_data.get("competitions", [])
            if not competitions:
                # Fallback to top-level event if no competitions
                event = self._parse_tournament_event(event_data, event_data, league, sport)
                if event:
                    events.append(event)
                continue

            for comp_data in competitions:
                event = self._parse_tournament_event(event_data, comp_data, league, sport)
                if event:
                    # Filter by target_date in user timezone
                    if to_user_tz(event.start_time).date() == target_date:
                        events.append(event)

        return events

    def _parse_tournament_event(
        self, event_data: dict, comp_data: dict, league: str, sport: str
    ) -> Event | None:
        """Parse a tournament-style competition (session, round, etc.).

        Args:
            event_data: Top-level event data (Grand Prix name, etc.)
            comp_data: Specific competition/session data
            league: League code
            sport: Sport name

        Returns:
            Event object or None
        """
        try:
            event_id = comp_data.get("id") or event_data.get("id", "")
            if not event_id:
                return None

            # Parse start time from competition
            date_str = comp_data.get("date") or event_data.get("date")
            if not date_str:
                return None

            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            # Build name: "Grand Prix Name - Session Type"
            base_name = event_data.get("name", "")
            comp_type = comp_data.get("type", {})
            session_name = comp_type.get("shortDetail") or comp_type.get("abbreviation") or ""

            if session_name and session_name not in base_name:
                # Map abbreviations to friendly names for better matching
                session_map = {
                    "FP1": "Free Practice 1",
                    "FP2": "Free Practice 2",
                    "FP3": "Free Practice 3",
                    "Qual": "Qualifying",
                    "Race": "Race",
                    "SR": "Sprint Race",
                    "SS": "Sprint Shootout",
                    "SQ": "Sprint Qualifying",
                    "Sprint": "Sprint Qualifying",
                }
                friendly_session = session_map.get(session_name, session_name)
                event_name = f"{base_name} - {friendly_session}"
            else:
                event_name = base_name

            short_name = comp_data.get("shortName") or event_data.get("shortName") or event_name

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

            # Parse status from competition
            status_data = comp_data.get("status", {})
            type_data = status_data.get("type", {}) if status_data else {}
            state = type_data.get("state", "pre")

            if state == "in":
                status = EventStatus(state="live", detail=type_data.get("detail"))
            elif state == "post":
                status = EventStatus(state="final", detail=type_data.get("detail"))
            else:
                status = EventStatus(state="scheduled")

            # Parse venue
            venue = None
            venue_data = comp_data.get("venue") or event_data.get("venue")
            if not venue_data and "competitions" in event_data:
                # Sometimes venue is only in the first competition of the event
                venue_data = event_data["competitions"][0].get("venue")

            if venue_data:
                venue = Venue(
                    name=venue_data.get("fullName", ""),
                    city=venue_data.get("address", {}).get("city", ""),
                    state=venue_data.get("address", {}).get("state", ""),
                    country=venue_data.get("address", {}).get("country", ""),
                )

            # Parse broadcasts
            broadcasts = []
            for b in comp_data.get("broadcasts", []):
                names = b.get("names", [])
                broadcasts.extend(names)

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
                broadcasts=broadcasts,
            )

        except Exception as e:
            logger.warning("[ESPN_TOURNAMENT] Failed to parse event: %s", e)
            return None

    def _make_tournament_abbrev(self, name: str) -> str:
        """Make abbreviation for tournament name."""
        # Take first letters of significant words
        words = [w for w in name.split() if len(w) > 2]
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words[:4])
        return name[:6].upper()
