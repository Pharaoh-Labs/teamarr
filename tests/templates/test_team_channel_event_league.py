"""League variables on a team channel describe the game, not the team (#1220).

A team that follows several leagues carries one primary league. Every game on
its channel used to be rendered with that league, so a Champions League night
on an EPL club's channel read "EPL" under a description that said otherwise.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.filler.generator import FillerGenerator
from teamarr.core.types import Event, EventStatus, Team
from teamarr.services import league_mappings as lm
from teamarr.templates.context import TeamChannelContext
from teamarr.templates.context_builder import ContextBuilder
from teamarr.templates.resolver import TemplateResolver

PRIMARY = "eng.1"
CUP = "uefa.champions"
LEAGUE_VARS = "{league}|{league_name}|{league_id}|{league_code}|{gracenote_category}"


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _team(tid: str, name: str, league: str) -> Team:
    return Team(
        id=tid,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league=league,
        sport="soccer",
    )


def _event(eid: str, league: str, opponent: str) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{opponent} at Arsenal",
        short_name=f"{opponent[:3].upper()} @ ARS",
        start_time=datetime(2026, 11, 20, 20, tzinfo=UTC),
        home_team=_team("359", "Arsenal", PRIMARY),
        away_team=_team(f"opp-{eid}", opponent, league),
        status=EventStatus(state="scheduled"),
        league=league,
        sport="soccer",
    )


class _Service:
    """The two calls the context builder makes, recorded."""

    def __init__(self) -> None:
        self.stats_asked: set[tuple[str, str]] = set()

    def get_team_stats(self, team_id: str, league: str):
        self.stats_asked.add((team_id, league))
        return None

    def enrich_event_preview(self, event: Event) -> Event:
        return event


def _service() -> _Service:
    return _Service()


def _render(context, template: str = LEAGUE_VARS) -> list[str]:
    return TemplateResolver().resolve(template, context).split("|")


def _expected(league: str) -> list[str]:
    service = lm.get_league_mapping_service()
    return [
        service.get_league_alias(league),
        service.get_league_display_name(league),
        service.get_league_id(league),
        league,
        service.get_gracenote_category(league),
    ]


class TestEventProgrammeOnATeamChannel:
    def test_the_two_leagues_really_read_differently(self):
        # Guards the tests below against a league table where they coincide.
        assert _expected(PRIMARY) != _expected(CUP)
        assert all(a != b for a, b in zip(_expected(PRIMARY)[:4], _expected(CUP)[:4], strict=True))

    def test_a_cup_game_is_labelled_with_the_cup(self):
        """What TeamEPGGenerator passes: the event's league, the team's alongside."""
        context = ContextBuilder(_service()).build_for_event(
            _event("ucl-1", CUP, "Bayern Munich"), "359", CUP, team_league=PRIMARY
        )
        assert _render(context) == _expected(CUP)

    def test_a_league_game_is_unchanged(self):
        context = ContextBuilder(_service()).build_for_event(
            _event("epl-1", PRIMARY, "Chelsea"), "359", PRIMARY, team_league=PRIMARY
        )
        assert _render(context) == _expected(PRIMARY)

    def test_the_home_league_variable_stays_on_the_team(self):
        context = ContextBuilder(_service()).build_for_event(
            _event("ucl-1", CUP, "Bayern Munich"), "359", CUP, team_league=PRIMARY
        )
        assert _render(context, "{soccer_primary_league_id}") == [PRIMARY]

    def test_team_stats_stay_on_the_team_league_and_opponents_on_the_game(self):
        service = _service()
        ContextBuilder(service).build_for_event(
            _event("ucl-1", CUP, "Bayern Munich"),
            "359",
            CUP,
            team_league=PRIMARY,
            next_event=_event("epl-2", PRIMARY, "Chelsea"),
        )
        asked = service.stats_asked
        assert ("359", PRIMARY) in asked
        assert ("359", CUP) not in asked
        assert ("opp-ucl-1", CUP) in asked
        # The next game is described by its own league, not the current one's.
        assert ("opp-epl-2", PRIMARY) in asked

    def test_an_event_channel_context_is_untouched(self):
        """No team_league: everything reads the one league, as before."""
        service = _service()
        context = ContextBuilder(service).build_for_event(
            _event("ucl-1", CUP, "Bayern Munich"), "359", CUP
        )
        assert _render(context) == _expected(CUP)
        assert _render(context, "{soccer_primary_league_id}") == [CUP]
        assert ("359", CUP) in service.stats_asked


class TestGeneratorPassesTheEventLeague:
    def test_team_epg_builds_each_game_with_its_own_league(self):
        from teamarr.consumers.team_epg import TeamEPGGenerator

        generator = TeamEPGGenerator.__new__(TeamEPGGenerator)
        generator._context_builder = MagicMock()
        generator._event_to_programme = MagicMock(return_value=None)
        event = _event("ucl-1", CUP, "Bayern Munich")
        options = MagicMock()
        options.template = object()

        generator.render_event(
            event,
            team_id="359",
            league=PRIMARY,
            channel_id="Arsenal.epl",
            logo_url=None,
            options=options,
        )

        call = generator._context_builder.build_for_event.call_args
        assert call.args[2] == CUP
        assert call.kwargs["team_league"] == PRIMARY


class TestFillerOpponentStats:
    def test_next_and_last_games_look_up_the_opponent_in_their_own_league(self):
        filler = FillerGenerator.__new__(FillerGenerator)
        asked: list[tuple[str, str]] = []

        def record(event, team_id, league):
            asked.append((event.id, league))
            return MagicMock()

        filler._build_game_context = record
        team_config = TeamChannelContext(
            team_id="359", league=PRIMARY, sport="soccer", team_name="Arsenal"
        )

        filler._build_filler_context(
            team_config,
            None,
            next_event=_event("ucl-1", CUP, "Bayern Munich"),
            last_event=_event("epl-1", PRIMARY, "Chelsea"),
        )

        assert asked == [("ucl-1", CUP), ("epl-1", PRIMARY)]
