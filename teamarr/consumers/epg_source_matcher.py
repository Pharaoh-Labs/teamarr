"""Match EPG programme titles against TEAMARR sports API events.

Uses the existing matching infrastructure (classifier, TeamMatcher) to
find sports events in external EPG programme data.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    ClassifiedStream,
    StreamCategory,
    classify_stream,
)
from teamarr.core import Event
from teamarr.services import SportsDataService

logger = logging.getLogger(__name__)

# Programme start must be within this window of the API event start
_TIME_TOLERANCE = timedelta(hours=3)


class EPGProgrammeMatcher:
    """Matches EPG programme titles to sports API events."""

    def __init__(
        self,
        service: SportsDataService,
        search_leagues: list[str],
        user_tz: ZoneInfo | None = None,
    ):
        self._service = service
        self._search_leagues = search_leagues
        self._user_tz = user_tz or ZoneInfo("UTC")

    def match_programme(self, programme: dict) -> Event | None:
        """Try to match a single EPG programme to a sports event.

        Args:
            programme: Dict with 'title', 'start', 'stop', 'description' keys.

        Returns:
            Matched Event or None.
        """
        title = programme.get("title", "")
        if not title:
            return None

        classified = classify_stream(title)
        if classified.category == StreamCategory.PLACEHOLDER:
            return None

        if classified.category == StreamCategory.TEAM_VS_TEAM:
            return self._match_team_vs_team(classified, programme)

        if classified.category == StreamCategory.EVENT_CARD:
            return self._match_event_card(classified, programme)

        return None

    def _match_team_vs_team(
        self, classified: ClassifiedStream, programme: dict
    ) -> Event | None:
        team1 = classified.team1
        team2 = classified.team2
        if not team1 or not team2:
            return None

        prog_start = self._parse_programme_time(programme.get("start"))
        if not prog_start:
            return None

        target_date = prog_start.date()

        for league in self._search_leagues:
            try:
                events = self._service.get_events(league, target_date)
            except Exception:
                continue

            for event in events:
                if not self._times_match(prog_start, event.start_time):
                    continue

                if self._teams_match(team1, team2, event):
                    return event

        return None

    def _match_event_card(
        self, classified: ClassifiedStream, programme: dict
    ) -> Event | None:
        event_hint = classified.event_hint
        if not event_hint:
            return None

        prog_start = self._parse_programme_time(programme.get("start"))
        if not prog_start:
            return None

        target_date = prog_start.date()

        for league in self._search_leagues:
            try:
                events = self._service.get_events(league, target_date)
            except Exception:
                continue

            for event in events:
                if not self._times_match(prog_start, event.start_time):
                    continue
                if event_hint.lower() in event.name.lower():
                    return event

        return None

    def _teams_match(self, team1: str, team2: str, event: Event) -> bool:
        t1 = team1.lower().strip()
        t2 = team2.lower().strip()

        home_names = self._get_team_names(event.home_team)
        away_names = self._get_team_names(event.away_team)

        t1_matches_home = any(t1 in n for n in home_names)
        t1_matches_away = any(t1 in n for n in away_names)
        t2_matches_home = any(t2 in n for n in home_names)
        t2_matches_away = any(t2 in n for n in away_names)

        return (t1_matches_home and t2_matches_away) or (
            t1_matches_away and t2_matches_home
        )

    @staticmethod
    def _get_team_names(team) -> list[str]:
        if team is None:
            return []
        names = []
        for attr in ("name", "short_name", "abbreviation"):
            val = getattr(team, attr, None)
            if val:
                names.append(val.lower())
        return names

    def _times_match(self, prog_start: datetime, event_start: datetime) -> bool:
        if prog_start.tzinfo is None:
            prog_start = prog_start.replace(tzinfo=self._user_tz)
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=self._user_tz)
        return abs(prog_start - event_start) <= _TIME_TOLERANCE

    @staticmethod
    def _parse_programme_time(time_str: str | None) -> datetime | None:
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str)
        except (ValueError, TypeError):
            return None

    def match_programmes(
        self, programmes: list[dict]
    ) -> list[tuple[dict, Event | None]]:
        """Batch match programmes. Returns (programme, event_or_none) pairs."""
        results = []
        for prog in programmes:
            event = self.match_programme(prog)
            results.append((prog, event))
        return results
