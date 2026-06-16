"""Squiggle AFL data provider.

Normalizes Squiggle API responses into Teamarr's core types.
Replaces TSDB as the primary AFL provider — free, no API key required.

API contract (from https://api.squiggle.com.au/):
- game["complete"] = 0   → scheduled
- game["complete"] = 1-99 → live (value is completion %)
- game["complete"] = 100  → final
- game["date"]            → local Australian time (YYYY-MM-DD HH:MM:SS)
- game["unixtime"]        → UTC unix timestamp (authoritative for scheduling)
"""
import logging
from datetime import UTC, date, datetime, timedelta

from teamarr.core import (
    SEASON_POSTSEASON,
    SEASON_REGULAR,
    Event,
    EventStatus,
    LeagueMappingSource,
    SportsProvider,
    Team,
    TeamStats,
    Venue,
)
from teamarr.providers.squiggle.client import SquiggleClient

logger = logging.getLogger(__name__)

_SPORT = "australian-football"


class SquiggleProvider(SportsProvider):
    """AFL data provider backed by Squiggle.com.au."""

    def __init__(
        self,
        client: SquiggleClient | None = None,
        league_mapping_source: LeagueMappingSource | None = None,
    ):
        self._client = client or SquiggleClient()
        self._league_mapping_source = league_mapping_source

    @property
    def name(self) -> str:
        return "squiggle"

    def supports_league(self, league: str) -> bool:
        if not self._league_mapping_source:
            return False
        return self._league_mapping_source.supports_league(league, self.name)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        if not self.supports_league(league):
            return []

        logger.info("[SQUIGGLE] get_events league=%s date=%s", league, target_date)

        # Fetch full season and filter by date — single cached API call per hour
        games = self._client.get_games(target_date.year)
        teams_by_id = self._teams_by_id()

        events: list[Event] = []
        for game in games:
            if not self._game_on_date(game, target_date):
                continue
            event = self._parse_game(game, league, teams_by_id)
            if event:
                events.append(event)
        return events

    def get_team_schedule(self, team_id: str, league: str, days_ahead: int = 14) -> list[Event]:
        if not self.supports_league(league):
            return []

        logger.info(
            "[SQUIGGLE] get_team_schedule team=%s league=%s days_ahead=%d",
            team_id, league, days_ahead,
        )

        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        games = self._client.get_games(today.year)
        teams_by_id = self._teams_by_id()

        events: list[Event] = []
        for game in games:
            if str(game.get("hteamid")) != team_id and str(game.get("ateamid")) != team_id:
                continue
            game_date = self._game_date(game)
            if game_date is None or not (today <= game_date.date() <= end_date):
                continue
            event = self._parse_game(game, league, teams_by_id)
            if event:
                events.append(event)

        events.sort(key=lambda e: e.start_time)
        return events

    def get_team(self, team_id: str, league: str) -> Team | None:
        teams = self._client.get_teams()
        for t in teams:
            if str(t.get("id")) == team_id:
                return self._parse_team(t, league)
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        games = self._client.get_games(date.today().year)
        teams_by_id = self._teams_by_id()
        for game in games:
            if str(game.get("id")) == event_id:
                return self._parse_game(game, league, teams_by_id)
        return None

    def get_league_teams(self, league: str) -> list[Team]:
        if not self.supports_league(league):
            return []

        logger.info("[SQUIGGLE] get_league_teams league=%s", league)
        teams = self._client.get_teams()
        result = [self._parse_team(t, league) for t in teams]
        result = [t for t in result if t is not None]
        logger.info("[SQUIGGLE] Loaded %d teams for league=%s", len(result), league)
        return result

    def get_team_stats(self, team_id: str, league: str) -> TeamStats | None:
        if not self.supports_league(league):
            return None

        standings = self._client.get_standings(date.today().year)
        entry = next(
            (s for s in standings if str(s.get("id")) == team_id), None
        )
        if not entry:
            return None

        wins = entry.get("wins", 0) or 0
        losses = entry.get("losses", 0) or 0
        draws = entry.get("draws", 0) or 0
        played = entry.get("played") or 1  # avoid divide-by-zero

        record = f"{wins}-{losses}" if draws == 0 else f"{wins}-{losses}-{draws}"

        pts_for = entry.get("for") or 0
        pts_against = entry.get("against") or 0

        return TeamStats(
            record=record,
            wins=wins,
            losses=losses,
            ties=draws,
            rank=entry.get("rank"),
            ppg=round(pts_for / played, 1),
            papg=round(pts_against / played, 1),
        )

    def get_supported_leagues(self) -> list[str]:
        if not self._league_mapping_source:
            return []
        return [
            m.league_code
            for m in self._league_mapping_source.get_leagues_for_provider(self.name)
        ]

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _teams_by_id(self) -> dict[str, Team]:
        """Return a {str(id): Team} map for quick game parsing."""
        teams = self._client.get_teams()
        result: dict[str, Team] = {}
        for t in teams:
            team = self._parse_team(t, "afl")
            if team:
                result[team.id] = team
        return result

    def _game_date(self, game: dict) -> datetime | None:
        """Convert game unixtime to UTC datetime."""
        unix = game.get("unixtime")
        if not unix:
            return None
        try:
            return datetime.fromtimestamp(int(unix), tz=UTC)
        except Exception:
            return None

    def _game_on_date(self, game: dict, target_date: date) -> bool:
        """Check whether a game falls on target_date (in UTC)."""
        dt = self._game_date(game)
        if dt is None:
            return False
        return dt.date() == target_date

    @staticmethod
    def _parse_status(game: dict) -> EventStatus:
        complete = game.get("complete", 0) or 0
        if complete == 100:
            return EventStatus(state="final", detail="Full Time")
        if complete > 0:
            return EventStatus(state="live", detail=f"{complete}% complete")
        return EventStatus(state="scheduled")

    def _parse_team(self, t: dict, league: str) -> Team | None:
        team_id = str(t.get("id", ""))
        name = t.get("name") or ""
        if not team_id or not name:
            return None

        abbrev = t.get("abbrev") or name[:3].upper()
        logo_file = t.get("logo") or ""
        logo_url = SquiggleClient.logo_url(logo_file) if logo_file else None

        return Team(
            id=team_id,
            provider=self.name,
            name=name,
            short_name=name,   # Squiggle doesn't provide a separate short name
            abbreviation=abbrev,
            league=league,
            sport=_SPORT,
            logo_url=logo_url,
        )

    def _parse_game(
        self,
        game: dict,
        league: str,
        teams_by_id: dict[str, Team],
    ) -> Event | None:
        game_id = str(game.get("id", ""))
        if not game_id:
            return None

        start_time = self._game_date(game)
        if start_time is None:
            return None

        hid = str(game.get("hteamid", ""))
        aid = str(game.get("ateamid", ""))

        home_team = teams_by_id.get(hid) or Team(
            id=hid, provider=self.name,
            name=game.get("hteam") or "Unknown",
            short_name=game.get("hteam") or "Unknown",
            abbreviation=hid, league=league, sport=_SPORT,
        )
        away_team = teams_by_id.get(aid) or Team(
            id=aid, provider=self.name,
            name=game.get("ateam") or "Unknown",
            short_name=game.get("ateam") or "Unknown",
            abbreviation=aid, league=league, sport=_SPORT,
        )

        venue_name = game.get("venue")
        venue = Venue(name=venue_name) if venue_name else None

        complete = game.get("complete", 0) or 0
        home_score = game.get("hscore") if complete > 0 else None
        away_score = game.get("ascore") if complete > 0 else None

        season_type = SEASON_POSTSEASON if game.get("is_final") else SEASON_REGULAR

        name = f"{away_team.name} at {home_team.name}"
        short_name = f"{away_team.abbreviation} at {home_team.abbreviation}"

        return Event(
            id=game_id,
            provider=self.name,
            name=name,
            short_name=short_name,
            start_time=start_time,
            home_team=home_team,
            away_team=away_team,
            status=self._parse_status(game),
            league=league,
            sport=_SPORT,
            home_score=home_score,
            away_score=away_score,
            venue=venue,
            season_year=game.get("year"),
            season_type=season_type,
        )
