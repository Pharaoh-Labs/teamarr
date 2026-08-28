"""Normalize Bell Media's TSN widget API into Teamarr sports types."""

import logging
from datetime import UTC, date, datetime, timedelta

from teamarr.core import (
    SEASON_REGULAR,
    Event,
    EventStatus,
    LeagueMappingSource,
    SportsProvider,
    Team,
    TeamStats,
    Venue,
)
from teamarr.providers.base_client import BullpenConfig
from teamarr.providers.bellmedia.client import BellMediaClient

logger = logging.getLogger(__name__)


class BellMediaProvider(SportsProvider):
    """Bell Media implementation of SportsProvider."""

    DAYS_BACK = 7

    def __init__(
        self,
        league_mapping_source: LeagueMappingSource | None = None,
        client: BellMediaClient | None = None,
        bullpen: BullpenConfig | None = None,
    ):
        self._league_mapping_source = league_mapping_source
        self._client = client or BellMediaClient(
            league_mapping_source=league_mapping_source,
            bullpen=bullpen,
        )

    @property
    def name(self) -> str:
        return "bellmedia"

    def supports_league(self, league: str) -> bool:
        return self._client.supports_league(league)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        if not self.supports_league(league):
            return []
        teams = self._teams_by_id(league)
        # ±1-day superset — the API's `date` field is its own calendar, not
        # the user's; exact membership is the service seam's job (#590).
        return [
            event
            for row in self._client.get_events_between(
                league, target_date - timedelta(days=1), target_date + timedelta(days=1)
            )
            if (event := self._parse_event(row, league, teams)) is not None
        ]

    def get_team_schedule(
        self, team_id: str, league: str, days_ahead: int = 14
    ) -> list[Event]:
        if not self.supports_league(league):
            return []
        today = date.today()
        teams = self._teams_by_id(league)
        events = []
        for row in self._client.get_events_between(
            league, today - timedelta(days=self.DAYS_BACK), today + timedelta(days=days_ahead)
        ):
            event = self._parse_event(row, league, teams)
            if event and (event.home_team.id == str(team_id) or event.away_team.id == str(team_id)):
                events.append(event)
        events.sort(key=lambda event: event.start_time)
        return events

    def get_team(self, team_id: str, league: str) -> Team | None:
        for competitor in self._client.get_competitors(league):
            if str(competitor.get("competitorId")) == str(team_id):
                return self._parse_team(competitor, league)
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        row = self._client.get_event(league, event_id)
        return self._parse_event(row, league, self._teams_by_id(league)) if row else None

    def get_team_stats(self, team_id: str, league: str) -> TeamStats | None:
        return None

    def get_league_teams(self, league: str) -> list[Team]:
        if not self.supports_league(league):
            return []
        return [
            team
            for competitor in self._client.get_competitors(league)
            if (team := self._parse_team(competitor, league)) is not None
        ]

    def get_supported_leagues(self) -> list[str]:
        if not self._league_mapping_source:
            return []
        return [
            mapping.league_code
            for mapping in self._league_mapping_source.get_leagues_for_provider(self.name)
        ]

    def _sport(self, league: str) -> str:
        mapping = self._client.get_mapping(league)
        return mapping.sport if mapping else "football"

    def _teams_by_id(self, league: str) -> dict[str, Team]:
        return {
            team.id: team
            for competitor in self._client.get_competitors(league)
            if (team := self._parse_team(competitor, league)) is not None
        }

    def _parse_team(self, competitor: dict, league: str) -> Team | None:
        team_id = competitor.get("competitorId")
        name = competitor.get("name")
        if team_id is None or not name:
            return None
        return Team(
            id=str(team_id),
            provider=self.name,
            name=name,
            short_name=competitor.get("club") or name,
            abbreviation=competitor.get("shortName") or name[:3].upper(),
            league=league,
            sport=self._sport(league),
            color=competitor.get("primaryColor") or None,
        )

    def _parse_event(self, row: dict, league: str, teams: dict[str, Team]) -> Event | None:
        try:
            event_id = row.get("eventId")
            payload = row.get("event") or {}
            if event_id is None or not payload or payload.get("noTimeSet"):
                return None
            start_time = datetime.fromisoformat(payload["dateGMT"].replace("Z", "+00:00"))
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=UTC)
            away_team = self._parse_event_team(payload.get("top") or {}, teams, league)
            home_team = self._parse_event_team(payload.get("bottom") or {}, teams, league)
            if not away_team or not home_team:
                return None
            status = self._parse_status(payload)
            broadcasts = self._broadcasts(payload)
            return Event(
                id=str(event_id),
                provider=self.name,
                name=f"{away_team.name} at {home_team.name}",
                short_name=f"{away_team.abbreviation} at {home_team.abbreviation}",
                start_time=start_time,
                home_team=home_team,
                away_team=away_team,
                status=status,
                league=league,
                sport=self._sport(league),
                home_score=self._score(payload.get("bottom"), status),
                away_score=self._score(payload.get("top"), status),
                venue=Venue(name=payload["venue"]) if payload.get("venue") else None,
                broadcasts=broadcasts,
                season_year=row.get("season"),
                season_type=SEASON_REGULAR if row.get("seasonTypeId") == 1 else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("[BELLMEDIA] Failed to parse event: %s", exc)
            return None

    def _parse_event_team(self, data: dict, teams: dict[str, Team], league: str) -> Team | None:
        team_id = data.get("competitorId")
        if team_id is not None and str(team_id) in teams:
            return teams[str(team_id)]
        name = " ".join(part for part in (data.get("location"), data.get("name")) if part).strip()
        if not name:
            return None
        return Team(
            id=str(team_id) if team_id is not None else data.get("seoIdentifier", ""),
            provider=self.name,
            name=name,
            short_name=data.get("name") or name,
            abbreviation=data.get("shortName") or name[:3].upper(),
            league=league,
            sport=self._sport(league),
            color=data.get("primaryColor") or None,
        )

    @staticmethod
    def _parse_status(payload: dict) -> EventStatus:
        status = (payload.get("status") or "").lower()
        if status == "final":
            return EventStatus(state="final", detail=payload.get("formattedTime") or "Final")
        if status in {"in-progress", "in progress", "live"}:
            return EventStatus(state="live", detail=payload.get("formattedTime") or None)
        if "postpon" in status:
            return EventStatus(state="postponed", detail=payload.get("formattedTime") or None)
        if "cancel" in status:
            return EventStatus(state="cancelled", detail=payload.get("formattedTime") or None)
        return EventStatus(state="scheduled", detail=payload.get("formattedTime") or None)

    @staticmethod
    def _score(team: dict | None, status: EventStatus) -> int | None:
        if status.state == "scheduled" or not team:
            return None
        score = team.get("score")
        try:
            return int(score) if score is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _broadcasts(payload: dict) -> list[str]:
        broadcasts = [payload["broadcast"]] if payload.get("broadcast") else []
        broadcasts.extend(
            station.get("callLetters") or station.get("name")
            for station in payload.get("broadcastStations") or []
            if station.get("callLetters") or station.get("name")
        )
        return list(dict.fromkeys(broadcasts))
