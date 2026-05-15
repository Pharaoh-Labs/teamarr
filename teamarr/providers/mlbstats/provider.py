import logging
from datetime import UTC, date, datetime, timedelta

from teamarr.core import (
    SEASON_POSTSEASON,
    SEASON_PRESEASON,
    SEASON_REGULAR,
    Event,
    EventStatus,
    LeagueMappingSource,
    SportsProvider,
    Team,
    Venue,
)
from teamarr.providers.mlbstats.client import MLBStatsClient

logger = logging.getLogger(__name__)


class MLBStatsProvider(SportsProvider):
    # MLB StatsAPI gameType → canonical season_type.
    # Five playoff-series codes all map to postseason so consumer comparisons
    # (filter bypass, {is_playoff}) work without the consumer knowing MLB quirks.
    # 'A' (All Star) intentionally returns None — it's not a season-type.
    _GAMETYPE_CANONICAL: dict[str, str | None] = {
        "R": SEASON_REGULAR,
        "S": SEASON_PRESEASON,  # Spring Training
        "E": SEASON_PRESEASON,  # Exhibition
        "F": SEASON_POSTSEASON,  # Wild Card
        "D": SEASON_POSTSEASON,  # Division Series
        "L": SEASON_POSTSEASON,  # League Championship
        "W": SEASON_POSTSEASON,  # World Series
        "P": SEASON_POSTSEASON,  # Generic playoffs (minor leagues)
        "A": None,  # All Star
    }

    def __init__(
        self,
        client: MLBStatsClient | None = None,
        league_mapping_source: LeagueMappingSource | None = None,
    ):
        self._client = client or MLBStatsClient()
        self._league_mapping_source = league_mapping_source
        # Populated by get_league_teams; used to fill in abbreviation when
        # schedule hydration returns sparse team objects (id/name/link only).
        self._team_abbrev_cache: dict[str, str] = {}
        self._team_short_name_cache: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "mlbstats"

    def supports_league(self, league: str) -> bool:
        if not self._league_mapping_source:
            return False
        return self._league_mapping_source.supports_league(league, self.name)

    def _get_mapping(self, league: str):
        if not self._league_mapping_source:
            return None
        return self._league_mapping_source.get_mapping(league, self.name)

    def _get_sport_id(self, league: str) -> str | None:
        mapping = self._get_mapping(league)
        if not mapping:
            return None
        return mapping.provider_league_id

    def get_events(self, league: str, target_date: date) -> list[Event]:
        sport_id = self._get_sport_id(league)
        if not sport_id:
            return []

        logger.info(
            "[MLBSTATS] get_events league=%s sport_id=%s date=%s", league, sport_id, target_date
        )

        data = self._client.get_schedule(sport_id=sport_id, target_date=target_date)
        if not data:
            return []

        events: list[Event] = []
        for d in data.get("dates", []):
            for game in d.get("games", []):
                event = self._parse_game(game, league)
                if event:
                    events.append(event)
        return events

    def get_team_schedule(self, team_id: str, league: str, days_ahead: int = 14) -> list[Event]:
        sport_id = self._get_sport_id(league)
        if not sport_id:
            return []

        logger.info(
            "[MLBSTATS] get_team_schedule league=%s sport_id=%s team=%s", league, sport_id, team_id
        )

        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        data = self._client.get_schedule_range(
            sport_id=sport_id,
            start_date=today,
            end_date=end_date,
            team_id=team_id,
        )
        if not data:
            return []

        events: list[Event] = []
        for d in data.get("dates", []):
            for game in d.get("games", []):
                event = self._parse_game(game, league)
                if event:
                    events.append(event)

        events.sort(key=lambda e: e.start_time)
        return events

    def get_team(self, team_id: str, league: str) -> Team | None:
        data = self._client.get_team(team_id)
        if not data:
            return None

        teams = data.get("teams", [])
        if not teams:
            return None

        return self._parse_team(teams[0], league)

    def get_event(self, event_id: str, league: str) -> Event | None:
        # Intentionally unimplemented for now. Teamarr can work from schedule-based
        # event discovery, and MLB Stats API does not expose a simple single-event
        # endpoint in the shape the provider interface expects.
        return None

    def get_league_teams(self, league: str) -> list[Team]:
        sport_id = self._get_sport_id(league)
        if not sport_id:
            return []

        logger.info("[MLBSTATS] get_league_teams league=%s sport_id=%s", league, sport_id)

        data = self._client.get_teams(sport_id)
        if not data:
            logger.warning(
                "[MLBSTATS] No team data for league=%s sport_id=%s", league, sport_id
            )
            return []

        teams: list[Team] = []
        for team_data in data.get("teams", []):
            team = self._parse_team(team_data, league)
            if team:
                teams.append(team)
                if team.abbreviation:
                    self._team_abbrev_cache[team.id] = team.abbreviation
                if team.short_name and team.short_name != team.name:
                    self._team_short_name_cache[team.id] = team.short_name

        logger.info("[MLBSTATS] Loaded %d teams for league=%s", len(teams), league)
        return teams

    def get_supported_leagues(self) -> list[str]:
        if not self._league_mapping_source:
            return []
        return [
            m.league_code for m in self._league_mapping_source.get_leagues_for_provider(self.name)
        ]

    def _parse_team(self, team_data: dict, league: str) -> Team | None:
        team_id = str(team_data.get("id", ""))
        if not team_id:
            return None

        location = team_data.get("locationName", "") or ""
        team_name = team_data.get("teamName", "") or ""
        full_name = team_data.get("name") or f"{location} {team_name}".strip()

        abbrev = (
            team_data.get("abbreviation", "")
            or self._team_abbrev_cache.get(team_id, "")
            or team_name[:3].upper()
        )
        short_name = (
            team_name
            or self._team_short_name_cache.get(team_id, "")
            or full_name
        )

        return Team(
            id=team_id,
            provider=self.name,
            name=full_name,
            short_name=short_name,
            abbreviation=abbrev,
            league=league,
            sport="baseball",
            logo_url=f"https://www.mlbstatic.com/team-logos/{team_id}.svg",
            color=None,
        )

    def _parse_game(self, game: dict, league: str) -> Event | None:
        game_id = str(game.get("gamePk", ""))
        if not game_id:
            return None

        game_date = game.get("gameDate")
        if not game_date:
            return None

        try:
            start_time = datetime.fromisoformat(game_date.replace("Z", "+00:00")).astimezone(UTC)
        except Exception:
            return None

        teams_info = game.get("teams", {})
        away_info = teams_info.get("away", {})
        home_info = teams_info.get("home", {})

        away_team_raw = (away_info.get("team") or {})
        home_team_raw = (home_info.get("team") or {})

        away_team = self._parse_team(away_team_raw, league)
        home_team = self._parse_team(home_team_raw, league)
        if not away_team or not home_team:
            return None

        status_info = game.get("status", {})
        abstract_state = (status_info.get("abstractGameState") or "").lower()
        detailed_state = status_info.get("detailedState")

        state = "scheduled"
        if "final" in abstract_state:
            state = "final"
        elif abstract_state == "live":
            state = "live"
        elif "postponed" in (detailed_state or "").lower():
            state = "postponed"
        elif "cancelled" in (detailed_state or "").lower():
            state = "cancelled"

        venue_data = game.get("venue") or {}
        venue = None
        if venue_data.get("name"):
            venue = Venue(name=venue_data["name"])

        name = f"{away_team.name} at {home_team.name}"
        short_name = f"{away_team.short_name} at {home_team.short_name}"

        return Event(
            id=game_id,
            provider=self.name,
            name=name,
            short_name=short_name,
            start_time=start_time,
            home_team=home_team,
            away_team=away_team,
            status=EventStatus(state=state, detail=detailed_state),
            league=league,
            sport="baseball",
            home_score=home_info.get("score"),
            away_score=away_info.get("score"),
            venue=venue,
            broadcasts=[],
            season_year=(game.get("season") or 0) or None,
            season_type=self._GAMETYPE_CANONICAL.get(game.get("gameType") or ""),
        )
