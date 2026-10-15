"""Recurring franchise cricket: whole-season scoreboards, not team endpoints (#1069)."""

import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from teamarr.core.types import Event, Team
from teamarr.utilities.event_status import is_event_final

if TYPE_CHECKING:
    from teamarr.providers.espn.client import ESPNClient


class CricketSeriesMixin:
    """Shared season reads for events, imports, team history and previews.

    International ``panel:`` leagues keep their separate daily-panel path.
    ESPN's numeric franchise IDs and team IDs persist across seasons, but season
    labels do not follow one rule: BBL uses the start year, while SA20 went from
    2025/26 to 2027 with no season labelled 2026. Read the default link's explicit
    label plus the years near the requested day; never infer it from today's year
    alone. The client memoises these reads across all consumers.
    """

    if TYPE_CHECKING:
        # Provided by the host provider class (ESPNProvider).
        _client: ESPNClient

        def _get_sport_league_from_db(self, league: str) -> tuple[str, str] | None: ...

        def _parse_event(self, data: dict, league: str) -> Event | None: ...

        def _parse_team_from_teams_endpoint(
            self, team_data: dict, league: str, sport: str
        ) -> Team | None: ...

        @staticmethod
        def _event_has_team(team_id: str, event: Event) -> bool: ...

    def _cricket_series_id(self, league: str) -> str | None:
        pair = self._get_sport_league_from_db(league)
        if pair and pair[0] == "cricket" and pair[1].isdigit():
            return pair[1]
        return None

    def _cricket_series_payloads(self, league: str, years: set[int]) -> list[dict]:
        series_id = self._cricket_series_id(league)
        if not series_id:
            return []
        default = self._client.get_cricket_season(series_id)
        payloads = [default] if default else []
        # The default slate is often only one match, but supplies the authoritative
        # next/current season label, even before the new season starts.
        for meta in (default or {}).get("leagues") or []:
            for link in meta.get("links") or []:
                match = re.search(r"/season/(\d{4})(?:/|$)", link.get("href") or "")
                if match:
                    years = years | {int(match[1])}
        for year in sorted(years):
            payload = self._client.get_cricket_season(series_id, year)
            if payload:
                payloads.append(payload)
        return payloads

    def _cricket_series_events(self, league: str, years: set[int]) -> list[Event]:
        events: dict[str, Event] = {}
        for payload in self._cricket_series_payloads(league, years):
            for raw in payload.get("events") or []:
                # ESPN occasionally includes an empty {} alongside real fixtures.
                if not raw or not raw.get("id"):
                    continue
                event = self._parse_event(raw, league)
                if event:
                    event.series_slug = self._cricket_series_id(league) or ""
                    events[event.id] = event
        return sorted(events.values(), key=lambda e: e.start_time)

    def _get_cricket_series_events(self, league: str, day: date) -> list[Event]:
        # Whole-season timestamps are UTC, so these are UTC buckets. The service
        # unions neighbours and applies the user's day window, exactly as for
        # every other provider. No ESPN local-date filter can drop an MLC night.
        return [
            event
            for event in self._cricket_series_events(league, {day.year - 1, day.year})
            if event.start_time.date() == day
        ]

    def _get_cricket_series_teams(self, league: str) -> list[Team]:
        series_id = self._cricket_series_id(league)
        payload = self._client.get_cricket_season(series_id) if series_id else None
        teams = []
        for raw in (payload or {}).get("teams") or []:
            if (raw.get("name") or "").strip().upper() in {"TBA", "TBC", "TBD"}:
                continue
            team = self._parse_team_from_teams_endpoint(
                {**raw, "displayName": raw.get("displayName") or raw.get("name") or ""},
                league,
                "cricket",
            )
            if team:
                teams.append(team)
        return teams

    def _get_cricket_series_team_schedule(
        self, team_id: str, league: str, days_ahead: int
    ) -> list[Event]:
        today = date.today()
        end = today + timedelta(days=days_ahead)
        years = set(range(today.year - 1, end.year + 1))
        return [
            event
            for event in self._cricket_series_events(league, years)
            if self._event_has_team(team_id, event)
            and (is_event_final(event) or event.start_time.date() <= end)
        ]

    def _get_cricket_series_recent_final(self, league: str) -> Event | None:
        today = date.today()
        now = datetime.now(UTC)
        events = self._cricket_series_events(league, {today.year - 1, today.year})
        return next(
            (
                event
                for event in reversed(events)
                if is_event_final(event) and event.start_time <= now
            ),
            None,
        )
