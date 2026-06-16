"""Supabase sports data provider.

Implements SportsProvider for leagues backed by Supabase (CBL and future
leagues). Data shape mirrors the CBL schema; extend if a future league
uses different table names or field layouts.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

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
from teamarr.providers.supabase.client import SupabaseLeagueClient

logger = logging.getLogger(__name__)

# CBL games are played in Ontario — all schedule times are Eastern
_EASTERN = ZoneInfo("America/Toronto")


class SupabaseProvider(SportsProvider):
    """SportsProvider implementation for Supabase-backed leagues (e.g. CBL)."""

    def __init__(
        self,
        league_mapping_source: LeagueMappingSource | None = None,
        client: SupabaseLeagueClient | None = None,
    ):
        self._league_mapping_source = league_mapping_source
        self._client = client or SupabaseLeagueClient(
            league_mapping_source=league_mapping_source,
        )

    @property
    def name(self) -> str:
        return "supabase"

    def supports_league(self, league: str) -> bool:
        return self._client.supports_league(league)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        entries = self._client.get_events_by_date(league, target_date)
        teams_by_city = self._build_teams_by_city(league)
        events = []
        for entry in entries:
            event = self._parse_event(entry, teams_by_city, league)
            if event:
                events.append(event)
        return events

    def get_team_schedule(
        self,
        team_id: str,
        league: str,
        days_ahead: int = 14,
    ) -> list[Event]:
        entries = self._client.get_team_schedule(league, team_id, days_ahead)
        teams_by_city = self._build_teams_by_city(league)
        events = []
        for entry in entries:
            event = self._parse_event(entry, teams_by_city, league)
            if event:
                events.append(event)
        events.sort(key=lambda e: e.start_time)
        return events

    def get_team(self, team_id: str, league: str) -> Team | None:
        teams_data = self._client.get_teams(league)
        logo_map = self._client.get_logo_map(league)
        sport = self._client.get_sport(league)
        for t in teams_data:
            if t.get("id") == team_id:
                return self._parse_team(t, logo_map, league, sport)
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        schedule = self._client.get_schedule(league)
        completed = self._client.get_completed_games(league)
        score_map = self._client.build_score_map(completed)
        teams_by_city = self._build_teams_by_city(league)

        for entry in schedule:
            if entry.get("id") == event_id:
                merged = self._client._merge_scores([entry], score_map)
                return self._parse_event(merged[0], teams_by_city, league)
        return None

    def get_team_stats(self, team_id: str, league: str) -> TeamStats | None:
        return None

    def get_league_teams(self, league: str) -> list[Team]:
        teams_data = self._client.get_teams(league)
        logo_map = self._client.get_logo_map(league)
        sport = self._client.get_sport(league)
        teams = []
        for t in teams_data:
            team = self._parse_team(t, logo_map, league, sport)
            if team:
                teams.append(team)
        return teams

    def get_supported_leagues(self) -> list[str]:
        if not self._league_mapping_source:
            return []
        mappings = self._league_mapping_source.get_leagues_for_provider("supabase")
        return [m.league_code for m in mappings]

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _build_teams_by_city(self, league: str) -> dict[str, Team]:
        """Build {city_lower: Team} map for resolving schedule entries.

        Two fallback layers handle common CBL data quirks:
        - Hyphenated cities: "Chatham-Kent" also indexed as "chatham" so the
          schedule's "Chatham" override resolves correctly.
        - Missing city: teams with city=None are indexed by the first word of
          their team name (e.g., "Hamilton Cardinals" → "hamilton").

        Exact city matches take precedence; fallbacks only fill gaps.
        """
        teams_data = self._client.get_teams(league)
        logo_map = self._client.get_logo_map(league)
        sport = self._client.get_sport(league)

        primary: dict[str, Team] = {}   # exact city matches
        fallback: dict[str, Team] = {}  # first-component / first-word

        for t in teams_data:
            team = self._parse_team(t, logo_map, league, sport)
            if not team:
                continue

            city = t.get("city")
            team_name = t.get("team_name", "")

            if city:
                city_lower = city.lower()
                primary[city_lower] = team
                # Hyphenated cities (e.g., "Chatham-Kent") — also index by
                # the part before the first hyphen so schedule abbreviations
                # like "Chatham" still resolve.
                first = city.split("-")[0].lower()
                if first != city_lower and first not in fallback:
                    fallback[first] = team
            elif team_name:
                # No city on record — use first word of team name.
                first = team_name.split()[0].lower()
                if first and first not in fallback:
                    fallback[first] = team

        result = fallback.copy()
        result.update(primary)  # exact matches win
        return result

    def _parse_team(
        self,
        team_data: dict,
        logo_map: dict[str, str],
        league: str,
        sport: str,
    ) -> Team | None:
        team_id = team_data.get("id")
        if not team_id:
            return None

        name = team_data.get("team_name") or team_id
        city = team_data.get("city") or ""
        logo_url = logo_map.get(team_id)
        color = self._normalize_color(team_data.get("team_colors"))

        return Team(
            id=team_id,
            provider=self.name,
            name=name,
            short_name=city or name,
            abbreviation=self._make_abbrev(name),
            league=league,
            sport=sport,
            logo_url=logo_url,
            color=color,
        )

    def _parse_event(
        self,
        entry: dict,
        teams_by_city: dict[str, Team],
        league: str,
    ) -> Event | None:
        try:
            event_id = entry.get("id")
            if not event_id:
                return None

            away_city = (entry.get("away_team_override") or "").lower()
            home_city = (entry.get("home_team_override") or "").lower()

            away_team = teams_by_city.get(away_city)
            home_team = teams_by_city.get(home_city)
            if not away_team or not home_team:
                logger.debug(
                    "[SUPABASE] Could not resolve teams for event %s "
                    "(away=%s, home=%s)",
                    event_id,
                    away_city,
                    home_city,
                )
                return None

            start_time = self._parse_datetime(entry)
            if not start_time:
                return None

            sport = self._client.get_sport(league)
            score_data = entry.get("_score")
            status = self._parse_status(entry, score_data)

            home_score: int | None = None
            away_score: int | None = None
            if score_data:
                home_score = self._parse_score(score_data.get("home_score"))
                away_score = self._parse_score(score_data.get("away_score"))

            venue = self._parse_venue(entry)

            event_name = f"{away_team.name} at {home_team.name}"
            short_name = f"{away_team.abbreviation} @ {home_team.abbreviation}"

            return Event(
                id=event_id,
                provider=self.name,
                name=event_name,
                short_name=short_name,
                start_time=start_time,
                home_team=home_team,
                away_team=away_team,
                status=status,
                league=league,
                sport=sport,
                home_score=home_score,
                away_score=away_score,
                venue=venue,
                broadcasts=[],
                season_type=SEASON_REGULAR,
            )
        except Exception as e:
            logger.warning(
                "[SUPABASE] Failed to parse event %s: %s",
                entry.get("id", "unknown"),
                e,
            )
            return None

    def _parse_datetime(self, entry: dict) -> datetime | None:
        """Parse game start time from schedule entry.

        game_date_override is an ISO date string ("2026-05-14").
        game_time_override is a 12-hour time string ("7:38 PM").
        Times are Eastern (America/Toronto) — CBL is Ontario-based.
        """
        date_str = entry.get("game_date_override")
        time_str = entry.get("game_time_override")
        if not date_str:
            return None

        if time_str:
            # Normalize: some entries use "7:05 PM", others "19:05"
            time_str = time_str.strip()
            for fmt in ("%I:%M %p", "%H:%M"):
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", f"%Y-%m-%d {fmt}")
                    return dt.replace(tzinfo=_EASTERN)
                except ValueError:
                    continue

        # Date only — use midnight Eastern
        try:
            dt = datetime.fromisoformat(date_str)
            return dt.replace(tzinfo=_EASTERN)
        except ValueError:
            return None

    def _parse_status(self, entry: dict, score_data: dict | None) -> EventStatus:
        raw_status = (entry.get("status") or "").lower()

        if raw_status == "postponed":
            return EventStatus(state="postponed", detail="Postponed")

        if raw_status == "cancelled":
            return EventStatus(state="cancelled", detail="Cancelled")

        if score_data:
            return EventStatus(state="final", detail="Final")

        return EventStatus(state="scheduled", detail=None)

    def _parse_venue(self, entry: dict) -> Venue | None:
        venue_name = entry.get("venue_override")
        if not venue_name:
            return None
        return Venue(name=venue_name)

    def _parse_score(self, score) -> int | None:
        if score is None or score == "":
            return None
        try:
            return int(score)
        except (ValueError, TypeError):
            return None

    def _normalize_color(self, color: str | None) -> str | None:
        if not color:
            return None
        color = color.strip()
        if color and not color.startswith("#"):
            color = f"#{color}"
        return color or None

    def _make_abbrev(self, team_name: str) -> str:
        """Return first 3 characters of team name, uppercase."""
        if not team_name:
            return ""
        return team_name[:3].upper()
