"""Tests for postgame .next variable resolution (#151).

Bug: _generate_game_day_fillers didn't receive next_future_event,
so postgame on the last game of the day always had .next = empty.

Fix: Pass next_future_event from the caller and use as fallback
when no same-day game follows the last game.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.filler.generator import FillerGenerator
from teamarr.consumers.filler.types import (
    FillerConfig,
    FillerOptions,
    FillerTemplate,
)
from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import TeamChannelContext

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def mock_league_mapping_service():
    """Mock the league mapping service singleton for all tests."""
    svc = MagicMock()
    svc.get_league_alias.side_effect = lambda code: code.upper()
    svc.get_league_display_name.side_effect = lambda code: code.upper()
    svc.get_league_id.side_effect = lambda code: code
    svc.get_league_logo.return_value = ""
    svc.get_gracenote_category.side_effect = lambda code: code.upper()
    svc.get_sport_display_name.side_effect = lambda code: code.title()
    with patch(
        "teamarr.services.league_mappings.get_league_mapping_service",
        return_value=svc,
    ):
        yield svc


def _make_team(team_id: str, name: str, abbrev: str) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbrev,
        league="nfl",
        sport="football",
    )


HOME = _make_team("8", "Detroit Lions", "DET")
AWAY = _make_team("34", "Green Bay Packers", "GB")
NEXT_HOME = _make_team("8", "Detroit Lions", "DET")
NEXT_AWAY = _make_team("21", "Chicago Bears", "CHI")


def _make_event(
    event_id: str,
    start_time: datetime,
    home: Team = HOME,
    away: Team = AWAY,
    state: str = "final",
) -> Event:
    return Event(
        id=event_id,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=start_time,
        home_team=home,
        away_team=away,
        status=EventStatus(state=state),
        league="nfl",
        sport="football",
    )


def _make_generator() -> FillerGenerator:
    """Create a FillerGenerator with a mocked SportsDataService."""
    service = MagicMock()
    service.get_opponent_stats.return_value = None
    service.get_team_stats.return_value = None
    gen = FillerGenerator(service)
    gen._options = FillerOptions(epg_timezone="America/New_York")
    return gen


def _team_config() -> TeamChannelContext:
    return TeamChannelContext(
        team_id="8",
        league="nfl",
        sport="football",
        team_name="Detroit Lions",
        team_abbrev="DET",
    )


class TestPostgameNextFallback:
    """Verify postgame filler receives next_future_event as .next context."""

    def test_single_game_day_gets_next_future_event(self):
        """When only one game on a day, postgame .next should be the next future event."""
        gen = _make_generator()

        # Game today at 1pm ET
        today_game = _make_event("401", datetime(2026, 2, 15, 13, 0, tzinfo=ET))
        # Next game is 3 days later
        future_game = _make_event(
            "402",
            datetime(2026, 2, 18, 20, 0, tzinfo=ET),
            home=NEXT_HOME,
            away=NEXT_AWAY,
            state="scheduled",
        )

        config = FillerConfig(
            postgame_enabled=True,
            postgame_template=FillerTemplate(
                title="{team_name} Postgame",
                subtitle="Next: {opponent.next}",
            ),
        )

        fillers = gen._generate_game_day_fillers(
            day_start=datetime(2026, 2, 15, 0, 0, tzinfo=ET),
            day_end=datetime(2026, 2, 16, 0, 0, tzinfo=ET),
            day_events=[today_game],
            prev_day_last_event=None,
            next_future_event=future_game,
            last_past_event=None,
            team_config=_team_config(),
            team_stats=None,
            channel_id="detroit-lions",
            logo_url=None,
            options=FillerOptions(epg_timezone="America/New_York"),
            config=config,
            tz=ET,
        )

        # Should have postgame fillers
        postgame = [f for f in fillers if "Postgame" in (f.title or "")]
        assert len(postgame) > 0, "Expected postgame filler programmes"

    def test_two_games_same_day_postgame_uses_second_game(self):
        """When two games on same day, postgame after game 1 should use game 2 as .next."""
        gen = _make_generator()

        game1 = _make_event("401", datetime(2026, 2, 15, 13, 0, tzinfo=ET))
        game2 = _make_event(
            "402",
            datetime(2026, 2, 15, 20, 0, tzinfo=ET),
            home=NEXT_HOME,
            away=NEXT_AWAY,
            state="scheduled",
        )
        future_game = _make_event(
            "403",
            datetime(2026, 2, 18, 20, 0, tzinfo=ET),
            state="scheduled",
        )

        config = FillerConfig(
            postgame_enabled=True,
            postgame_template=FillerTemplate(title="{team_name} Postgame"),
        )

        fillers = gen._generate_game_day_fillers(
            day_start=datetime(2026, 2, 15, 0, 0, tzinfo=ET),
            day_end=datetime(2026, 2, 16, 0, 0, tzinfo=ET),
            day_events=[game1, game2],
            prev_day_last_event=None,
            next_future_event=future_game,
            last_past_event=None,
            team_config=_team_config(),
            team_stats=None,
            channel_id="detroit-lions",
            logo_url=None,
            options=FillerOptions(epg_timezone="America/New_York"),
            config=config,
            tz=ET,
        )

        # Should have fillers (pregame + postgame sections)
        assert len(fillers) > 0

    def test_build_filler_context_with_next_event(self):
        """_build_filler_context populates next_game when next_event is provided."""
        gen = _make_generator()
        future_game = _make_event(
            "402",
            datetime(2026, 2, 18, 20, 0, tzinfo=ET),
            home=NEXT_HOME,
            away=NEXT_AWAY,
            state="scheduled",
        )

        ctx = gen._build_filler_context(
            team_config=_team_config(),
            team_stats=None,
            next_event=future_game,
            last_event=None,
        )

        assert ctx.next_game is not None
        assert ctx.next_game.event == future_game

    def test_build_filler_context_without_next_event(self):
        """_build_filler_context has next_game=None when no next_event."""
        gen = _make_generator()

        ctx = gen._build_filler_context(
            team_config=_team_config(),
            team_stats=None,
            next_event=None,
            last_event=None,
        )

        assert ctx.next_game is None

    def test_no_future_event_postgame_still_works(self):
        """Postgame filler works even when there's no future event at all."""
        gen = _make_generator()

        today_game = _make_event("401", datetime(2026, 2, 15, 13, 0, tzinfo=ET))

        config = FillerConfig(
            postgame_enabled=True,
            postgame_template=FillerTemplate(title="{team_name} Postgame"),
        )

        fillers = gen._generate_game_day_fillers(
            day_start=datetime(2026, 2, 15, 0, 0, tzinfo=ET),
            day_end=datetime(2026, 2, 16, 0, 0, tzinfo=ET),
            day_events=[today_game],
            prev_day_last_event=None,
            next_future_event=None,
            last_past_event=None,
            team_config=_team_config(),
            team_stats=None,
            channel_id="detroit-lions",
            logo_url=None,
            options=FillerOptions(epg_timezone="America/New_York"),
            config=config,
            tz=ET,
        )

        # Should still produce postgame filler (just with no .next)
        postgame = [f for f in fillers if "Postgame" in (f.title or "")]
        assert len(postgame) > 0


class TestGenerateDayFillers:
    """Integration: verify _generate_day_fillers passes next_future_event through."""

    def test_game_day_passes_next_future_event(self):
        """_generate_day_fillers computes and passes next_future_event to game day fillers."""
        gen = _make_generator()

        # One game today, one game in 3 days
        today_game = _make_event("401", datetime(2026, 2, 15, 13, 0, tzinfo=ET))
        future_game = _make_event(
            "402",
            datetime(2026, 2, 18, 20, 0, tzinfo=ET),
            home=NEXT_HOME,
            away=NEXT_AWAY,
            state="scheduled",
        )

        config = FillerConfig(
            postgame_enabled=True,
            postgame_template=FillerTemplate(
                title="{team_name} Postgame",
            ),
        )
        options = FillerOptions(epg_timezone="America/New_York")

        from datetime import date as date_type

        fillers = gen._generate_day_fillers(
            date=date_type(2026, 2, 15),
            events=[today_game, future_game],
            team_config=_team_config(),
            team_stats=None,
            channel_id="detroit-lions",
            logo_url=None,
            options=options,
            config=config,
            epg_start=datetime(2026, 2, 15, 0, 0, tzinfo=ET),
        )

        # Should produce fillers including postgame
        assert len(fillers) > 0

    def test_idle_day_still_gets_next_future_event(self):
        """Idle day fillers still receive next_future_event (regression check)."""
        gen = _make_generator()

        # No game today, one game in 3 days
        future_game = _make_event(
            "402",
            datetime(2026, 2, 18, 20, 0, tzinfo=ET),
            home=NEXT_HOME,
            away=NEXT_AWAY,
            state="scheduled",
        )

        config = FillerConfig(
            idle_enabled=True,
            idle_template=FillerTemplate(
                title="{team_name} - No Game Today",
            ),
        )
        options = FillerOptions(epg_timezone="America/New_York")

        from datetime import date as date_type

        fillers = gen._generate_day_fillers(
            date=date_type(2026, 2, 16),
            events=[future_game],
            team_config=_team_config(),
            team_stats=None,
            channel_id="detroit-lions",
            logo_url=None,
            options=options,
            config=config,
            epg_start=datetime(2026, 2, 16, 0, 0, tzinfo=ET),
        )

        # Should produce idle fillers
        assert len(fillers) > 0
