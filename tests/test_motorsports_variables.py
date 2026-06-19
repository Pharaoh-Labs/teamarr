"""Tests for motorsports template variables (F1, NASCAR, ...).

Verifies extractors in teamarr/templates/variables/motorsports.py for:
- Event/circuit identity (race_name, circuit_name)
- Session identity for the current channel (session_name, session_type,
  next_session_name, next_session_time)
- Grid/qualifying (pole_position, pole_team, grid)
- Race results (race_winner, podium_2, podium_3, podium, results,
  fastest_lap_driver)
- Non-racing events return empty strings for all of these.
"""

from datetime import UTC, datetime

from teamarr.core import Event, EventStatus, RacingResult, RacingSession, Team
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.motorsports import (
    extract_circuit_name,
    extract_fastest_lap_driver,
    extract_grid,
    extract_next_session_name,
    extract_next_session_time,
    extract_podium,
    extract_podium_2,
    extract_podium_3,
    extract_pole_position,
    extract_pole_team,
    extract_race_name,
    extract_race_winner,
    extract_results,
    extract_session_name,
    extract_session_type,
)

EVENT_TEAM = Team(
    id="event_600123",
    provider="espn",
    name="Monaco Grand Prix",
    short_name="Monaco GP",
    abbreviation="MGP",
    league="f1",
    sport="racing",
)


def _session(code: str, name: str, hour: int, results: list[RacingResult]) -> RacingSession:
    return RacingSession(
        code=code,
        name=name,
        start_time=datetime(2026, 5, 22 + (hour // 24), hour % 24, 0, tzinfo=UTC),
        results=results,
    )


QUALIFYING_RESULTS = [
    RacingResult(driver_name="Charles Leclerc", team_name="Ferrari", position=1),
    RacingResult(driver_name="Max Verstappen", team_name="Red Bull Racing", position=2),
    RacingResult(driver_name="Lando Norris", team_name="McLaren", position=3),
]

RACE_RESULTS = [
    RacingResult(
        driver_name="Max Verstappen",
        team_name="Red Bull Racing",
        position=1,
        fastest_lap=True,
    ),
    RacingResult(driver_name="Charles Leclerc", team_name="Ferrari", position=2),
    RacingResult(driver_name="Lando Norris", team_name="McLaren", position=3),
]

RACE_RESULTS_NOT_FINISHED = [
    RacingResult(driver_name="Max Verstappen", team_name="Red Bull Racing", grid_position=1),
    RacingResult(driver_name="Charles Leclerc", team_name="Ferrari", grid_position=2),
]


def _f1_event(sessions: list[RacingSession]) -> Event:
    return Event(
        id="600123",
        provider="espn",
        name="Monaco Grand Prix",
        short_name="Monaco GP",
        start_time=datetime(2026, 5, 24, 13, 0, tzinfo=UTC),
        home_team=EVENT_TEAM,
        away_team=EVENT_TEAM,
        status=EventStatus(state="post"),
        league="f1",
        sport="racing",
        circuit_name="Circuit de Monaco",
        sessions=sessions,
    )


NON_RACING_TEAM = Team(
    id="1",
    provider="espn",
    name="Detroit Lions",
    short_name="Lions",
    abbreviation="DET",
    league="nfl",
    sport="football",
)


def _non_racing_event() -> Event:
    return Event(
        id="1",
        provider="espn",
        name="Bears at Lions",
        short_name="CHI @ DET",
        start_time=datetime(2026, 1, 5, 18, 0, tzinfo=UTC),
        home_team=NON_RACING_TEAM,
        away_team=NON_RACING_TEAM,
        status=EventStatus(state="scheduled"),
        league="nfl",
        sport="football",
    )


def _ctx(event: Event | None, card_segment: str | None = None) -> TemplateContext:
    game_ctx = None
    if event:
        game_ctx = GameContext(event=event, card_segment=card_segment)
    return TemplateContext(game_context=game_ctx, team_config=None, team_stats=None)


# Pre-race weekend: practice done, qualifying done, race not yet run.
PRE_RACE_EVENT = _f1_event(
    [
        _session("fp1", "Practice 1", 0, []),
        _session("qualifying", "Qualifying", 12, QUALIFYING_RESULTS),
        _session("race", "Race", 36, RACE_RESULTS_NOT_FINISHED),
    ]
)

# Completed race weekend.
FINISHED_EVENT = _f1_event(
    [
        _session("fp1", "Practice 1", 0, []),
        _session("qualifying", "Qualifying", 12, QUALIFYING_RESULTS),
        _session("race", "Race", 36, RACE_RESULTS),
    ]
)


class TestEventAndCircuit:
    def test_race_name(self):
        ctx = _ctx(FINISHED_EVENT)
        assert extract_race_name(ctx, ctx.game_context) == "Monaco Grand Prix"

    def test_circuit_name(self):
        ctx = _ctx(FINISHED_EVENT)
        assert extract_circuit_name(ctx, ctx.game_context) == "Circuit de Monaco"

    def test_non_racing_event_returns_empty(self):
        ctx = _ctx(_non_racing_event())
        assert extract_race_name(ctx, ctx.game_context) == ""
        assert extract_circuit_name(ctx, ctx.game_context) == ""

    def test_no_game_context_returns_empty(self):
        ctx = _ctx(None)
        assert extract_race_name(ctx, ctx.game_context) == ""


class TestSessionIdentity:
    def test_session_name_and_type(self):
        ctx = _ctx(FINISHED_EVENT, card_segment="qualifying")
        assert extract_session_name(ctx, ctx.game_context) == "Qualifying"
        assert extract_session_type(ctx, ctx.game_context) == "qualifying"

    def test_session_name_for_practice(self):
        ctx = _ctx(FINISHED_EVENT, card_segment="fp1")
        assert extract_session_name(ctx, ctx.game_context) == "Practice 1"

    def test_next_session_name_and_time(self):
        ctx = _ctx(FINISHED_EVENT, card_segment="fp1")
        assert extract_next_session_name(ctx, ctx.game_context) == "Qualifying"
        assert extract_next_session_time(ctx, ctx.game_context) != ""

    def test_last_session_has_no_next(self):
        ctx = _ctx(FINISHED_EVENT, card_segment="race")
        assert extract_next_session_name(ctx, ctx.game_context) == ""
        assert extract_next_session_time(ctx, ctx.game_context) == ""

    def test_no_segment_returns_empty(self):
        ctx = _ctx(FINISHED_EVENT, card_segment=None)
        assert extract_session_name(ctx, ctx.game_context) == ""
        assert extract_session_type(ctx, ctx.game_context) == ""


class TestGridAndQualifying:
    def test_pole_position_and_team(self):
        ctx = _ctx(FINISHED_EVENT)
        assert extract_pole_position(ctx, ctx.game_context) == "Charles Leclerc"
        assert extract_pole_team(ctx, ctx.game_context) == "Ferrari"

    def test_grid_order(self):
        ctx = _ctx(FINISHED_EVENT)
        grid = extract_grid(ctx, ctx.game_context)
        lines = grid.split("\n")
        assert lines[0] == "1. Charles Leclerc (Ferrari)"
        assert lines[1] == "2. Max Verstappen (Red Bull Racing)"
        assert lines[2] == "3. Lando Norris (McLaren)"

    def test_no_qualifying_session_returns_empty(self):
        event = _f1_event([_session("race", "Race", 0, RACE_RESULTS)])
        ctx = _ctx(event)
        assert extract_pole_position(ctx, ctx.game_context) == ""
        assert extract_grid(ctx, ctx.game_context) == ""


class TestRaceResults:
    def test_race_winner_and_podium(self):
        ctx = _ctx(FINISHED_EVENT)
        assert extract_race_winner(ctx, ctx.game_context) == "Max Verstappen"
        assert extract_podium_2(ctx, ctx.game_context) == "Charles Leclerc"
        assert extract_podium_3(ctx, ctx.game_context) == "Lando Norris"
        assert (
            extract_podium(ctx, ctx.game_context)
            == "1. Max Verstappen, 2. Charles Leclerc, 3. Lando Norris"
        )

    def test_results_full_order(self):
        ctx = _ctx(FINISHED_EVENT)
        results = extract_results(ctx, ctx.game_context)
        lines = results.split("\n")
        assert lines[0] == "1. Max Verstappen (Red Bull Racing)"
        assert lines[2] == "3. Lando Norris (McLaren)"

    def test_fastest_lap_driver(self):
        ctx = _ctx(FINISHED_EVENT)
        assert extract_fastest_lap_driver(ctx, ctx.game_context) == "Max Verstappen"

    def test_pre_race_has_no_results(self):
        ctx = _ctx(PRE_RACE_EVENT)
        assert extract_race_winner(ctx, ctx.game_context) == ""
        assert extract_podium(ctx, ctx.game_context) == ""
        assert extract_results(ctx, ctx.game_context) == ""
        assert extract_fastest_lap_driver(ctx, ctx.game_context) == ""

    def test_non_racing_event_returns_empty(self):
        ctx = _ctx(_non_racing_event())
        assert extract_race_winner(ctx, ctx.game_context) == ""
        assert extract_results(ctx, ctx.game_context) == ""
