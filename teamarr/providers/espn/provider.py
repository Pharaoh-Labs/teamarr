"""ESPN sports data provider.

Fetches data from ESPN API and normalizes into our dataclass format.
"""

import logging
from datetime import UTC, date, datetime

from teamarr.core import Event, EventStatus, SportsProvider, Team, Venue
from teamarr.providers.espn.client import SPORT_MAPPING, ESPNClient

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_HALFTIME": "live",
    "STATUS_END_PERIOD": "live",
    "STATUS_FINAL": "final",
    "STATUS_FINAL_OT": "final",
    "STATUS_POSTPONED": "postponed",
    "STATUS_CANCELED": "cancelled",
    "STATUS_DELAYED": "scheduled",
}


class ESPNProvider(SportsProvider):
    """ESPN implementation of SportsProvider."""

    def __init__(self, client: ESPNClient | None = None):
        self._client = client or ESPNClient()

    @property
    def name(self) -> str:
        return "espn"

    def supports_league(self, league: str) -> bool:
        if league in SPORT_MAPPING:
            return True
        if "." in league:
            return True
        return False

    def get_events(self, league: str, target_date: date) -> list[Event]:
        date_str = target_date.strftime("%Y%m%d")
        data = self._client.get_scoreboard(league, date_str)
        if not data:
            return []

        events = []
        for event_data in data.get("events", []):
            event = self._parse_event(event_data, league)
            if event:
                events.append(event)

        return events

    def get_team_schedule(
        self,
        team_id: str,
        league: str,
        days_ahead: int = 14,
    ) -> list[Event]:
        data = self._client.get_team_schedule(league, team_id)
        if not data:
            return []

        now = datetime.now(UTC)
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)

        events = []
        for event_data in data.get("events", []):
            event = self._parse_event(event_data, league)
            if event and event.start_time >= cutoff:
                events.append(event)

        events.sort(key=lambda e: e.start_time)
        return events

    def get_team(self, team_id: str, league: str) -> Team | None:
        data = self._client.get_team(league, team_id)
        if not data:
            return None

        team_data = data.get("team", {})
        if not team_data:
            return None

        logo_url = self._extract_logo(team_data)

        return Team(
            id=team_data.get("id", team_id),
            provider=self.name,
            name=team_data.get("displayName", ""),
            short_name=team_data.get("shortDisplayName", ""),
            abbreviation=team_data.get("abbreviation", ""),
            league=league,
            logo_url=logo_url,
            color=team_data.get("color"),
        )

    def _extract_logo(self, data: dict) -> str | None:
        """Extract logo URL from team data. Handles 'logo' or 'logos' field."""
        if "logo" in data and data["logo"]:
            return data["logo"]
        logos = data.get("logos", [])
        if logos:
            for logo in logos:
                if "default" in logo.get("rel", []):
                    return logo.get("href")
            return logos[0].get("href")
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        data = self._client.get_event(league, event_id)
        if not data:
            return None

        header = data.get("header", {})
        competitions = header.get("competitions", [])
        if not competitions:
            return None

        competition = competitions[0]
        event_data = {
            "id": event_id,
            "name": header.get("gameNote", ""),
            "shortName": "",
            "date": competition.get("date"),
            "competitions": [competition],
        }

        return self._parse_event(event_data, league)

    def _parse_event(self, data: dict, league: str) -> Event | None:
        """Parse ESPN event data into Event dataclass."""
        try:
            event_id = data.get("id", "")
            if not event_id:
                return None

            competitions = data.get("competitions", [])
            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])
            if len(competitors) < 2:
                return None

            home_data = None
            away_data = None
            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_data = comp
                else:
                    away_data = comp

            if not home_data or not away_data:
                return None

            home_team = self._parse_team(home_data, league)
            away_team = self._parse_team(away_data, league)

            date_str = data.get("date") or competition.get("date", "")
            start_time = self._parse_datetime(date_str)
            if not start_time:
                return None

            status = self._parse_status(competition.get("status", {}))
            venue = self._parse_venue(competition.get("venue"))
            broadcasts = self._parse_broadcasts(competition.get("broadcasts", []))

            home_score = self._parse_score(home_data.get("score"))
            away_score = self._parse_score(away_data.get("score"))

            return Event(
                id=event_id,
                provider=self.name,
                name=data.get("name", ""),
                short_name=data.get("shortName", ""),
                start_time=start_time,
                home_team=home_team,
                away_team=away_team,
                status=status,
                league=league,
                home_score=home_score,
                away_score=away_score,
                venue=venue,
                broadcasts=broadcasts,
            )
        except Exception as e:
            logger.warning(f"Failed to parse event {data.get('id', 'unknown')}: {e}")
            return None

    def _parse_team(self, competitor: dict, league: str) -> Team:
        """Parse competitor data into Team."""
        team_data = competitor.get("team", {})
        return Team(
            id=team_data.get("id", competitor.get("id", "")),
            provider=self.name,
            name=team_data.get("displayName", ""),
            short_name=team_data.get("shortDisplayName", ""),
            abbreviation=team_data.get("abbreviation", ""),
            league=league,
            logo_url=team_data.get("logo"),
            color=team_data.get("color"),
        )

    def _parse_status(self, status_data: dict) -> EventStatus:
        """Parse status data into EventStatus."""
        type_data = status_data.get("type", {})
        espn_status = type_data.get("name", "STATUS_SCHEDULED")
        state = STATUS_MAP.get(espn_status, "scheduled")

        return EventStatus(
            state=state,
            detail=type_data.get("description"),
            period=status_data.get("period"),
            clock=status_data.get("displayClock"),
        )

    def _parse_venue(self, venue_data: dict | None) -> Venue | None:
        """Parse venue data into Venue."""
        if not venue_data:
            return None

        address = venue_data.get("address", {})
        return Venue(
            name=venue_data.get("fullName", ""),
            city=address.get("city"),
            state=address.get("state"),
            country=address.get("country"),
        )

    def _parse_broadcasts(self, broadcasts_data: list) -> list[str]:
        """Extract broadcast network names."""
        networks = []
        for broadcast in broadcasts_data:
            names = broadcast.get("names", [])
            networks.extend(names)
        return networks

    def _parse_datetime(self, date_str: str) -> datetime | None:
        """Parse ESPN date string to UTC datetime."""
        if not date_str:
            return None
        try:
            if date_str.endswith("Z"):
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.fromisoformat(date_str)
        except ValueError:
            return None

    def _parse_score(self, score) -> int | None:
        """Parse score to int. Handles string or dict format."""
        if score is None:
            return None
        try:
            if isinstance(score, dict):
                score = score.get("displayValue") or score.get("value")
            if score is None:
                return None
            return int(float(score))
        except (ValueError, TypeError):
            return None
