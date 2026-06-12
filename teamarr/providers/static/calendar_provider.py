"""Static calendar provider for racing leagues with no live API coverage.

Some racing series (e.g., IMSA, FIA WEC) are not available through ESPN or
TheSportsDB. This provider serves a hand-maintained JSON calendar of race
weekends and their sessions instead, so these leagues can still produce
session-based EPG entries via the same racing pipeline as ESPN-backed leagues.

The calendar data lives in `calendars/racing_calendars.json` and must be kept
up to date manually against each series' official season schedule.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

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

_SPORT = "racing"
_DEFAULT_DATA_PATH = Path(__file__).parent / "calendars" / "racing_calendars.json"


class StaticCalendarProvider(SportsProvider):
    """Racing data provider backed by a hand-maintained JSON calendar."""

    def __init__(
        self,
        data_path: Path | None = None,
        league_mapping_source: LeagueMappingSource | None = None,
    ):
        self._data_path = data_path or _DEFAULT_DATA_PATH
        self._league_mapping_source = league_mapping_source
        self._events_by_league: dict[str, list[Event]] = {}
        self._load()

    @property
    def name(self) -> str:
        return "static"

    def supports_league(self, league: str) -> bool:
        if not self._league_mapping_source:
            return False
        return self._league_mapping_source.supports_league(league, self.name)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        if not self.supports_league(league):
            return []

        events = self._events_by_league.get(league, [])
        return [
            e for e in events if any(s.start_time.date() == target_date for s in e.sessions)
        ]

    def get_team_schedule(self, team_id: str, league: str, days_ahead: int = 14) -> list[Event]:
        return []

    def get_team(self, team_id: str, league: str) -> Team | None:
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        for event in self._events_by_league.get(league, []):
            if event.id == event_id:
                return event
        return None

    def _load(self) -> None:
        try:
            with open(self._data_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "[STATIC] Failed to load calendar data from %s: %s", self._data_path, e
            )
            return

        for league, rounds in data.items():
            if league.startswith("_"):
                continue
            events = []
            for round_data in rounds:
                event = self._parse_round(round_data, league)
                if event:
                    events.append(event)
            events.sort(key=lambda e: e.start_time)
            self._events_by_league[league] = events

    def _parse_round(self, data: dict, league: str) -> Event | None:
        try:
            event_id = data["id"]
            name = data["name"]
            short_name = data.get("short_name") or name

            sessions = []
            for session_data in data.get("sessions", []):
                sessions.append(
                    RacingSession(
                        code=session_data["code"],
                        name=session_data["name"],
                        start_time=datetime.fromisoformat(session_data["start_time"]),
                    )
                )
            sessions.sort(key=lambda s: s.start_time)
            if not sessions:
                return None

            venue_data = data.get("venue") or {}
            venue = Venue(
                name=data.get("circuit_name", ""),
                city=venue_data.get("city"),
                state=venue_data.get("state"),
                country=venue_data.get("country"),
            )

            event_team = Team(
                id=f"event_{event_id}",
                provider=self.name,
                name=name,
                short_name=short_name[:20],
                abbreviation=self._make_abbrev(short_name),
                league=league,
                sport=_SPORT,
                logo_url=None,
                color=None,
            )

            return Event(
                id=event_id,
                provider=self.name,
                name=name,
                short_name=short_name,
                start_time=sessions[0].start_time,
                home_team=event_team,
                away_team=event_team,
                status=EventStatus(state="scheduled"),
                league=league,
                sport=_SPORT,
                venue=venue,
                broadcasts=[],
                circuit_name=data.get("circuit_name"),
                sessions=sessions,
            )
        except (KeyError, ValueError) as e:
            logger.warning(
                "[STATIC] Failed to parse round %r for league=%s: %s",
                data.get("id"), league, e,
            )
            return None

    @staticmethod
    def _make_abbrev(name: str) -> str:
        """Make abbreviation for an event name."""
        words = [w for w in name.split() if len(w) > 2]
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words[:4])
        return name[:6].upper()
