"""Tests for ESPN racing event parsing (F1, NASCAR, ...).

Verifies `_parse_racing_event` / `_parse_racing_session` in
teamarr/providers/espn/tournament.py for:
- A multi-session F1 race weekend (practice/qualifying/race), pre-race
  (grid only) and post-race (results + fastest lap).
- A single-session NASCAR-style event (no `type` block on the lone
  competition), which should degenerate to one "race" session.
"""

from teamarr.providers.espn.provider import ESPNProvider

provider = ESPNProvider()


def _competitor(order: int, full_name: str, statistics: list | None = None) -> dict:
    return {
        "order": order,
        "athlete": {"fullName": full_name},
        "statistics": statistics or [],
    }


F1_SCOREBOARD_EVENT = {
    "id": "600123",
    "name": "Monaco Grand Prix",
    "shortName": "Monaco GP",
    "date": "2026-05-24T13:00Z",
    "status": {"type": {"state": "post", "detail": "Final"}},
    "circuit": {
        "fullName": "Circuit de Monaco",
        "address": {"city": "Monte Carlo", "country": "Monaco"},
    },
    "competitions": [
        {
            "date": "2026-05-22T11:30Z",
            "type": {"abbreviation": "FP1"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Max Verstappen"),
                _competitor(2, "Charles Leclerc"),
            ],
        },
        {
            "date": "2026-05-23T14:00Z",
            "type": {"abbreviation": "Qual"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Charles Leclerc"),
                _competitor(2, "Max Verstappen"),
            ],
        },
        {
            "date": "2026-05-24T13:00Z",
            "type": {"abbreviation": "Race"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(
                    1,
                    "Max Verstappen",
                    statistics=[
                        {"name": "fastestLap", "value": True},
                        {"name": "points", "value": 25},
                    ],
                ),
                _competitor(
                    2,
                    "Charles Leclerc",
                    statistics=[{"name": "points", "value": 18}],
                ),
            ],
        },
    ],
}


# Pre-race weekend: only practice/qualifying have happened, race is scheduled.
F1_PRE_RACE_EVENT = {
    "id": "600124",
    "name": "Italian Grand Prix",
    "shortName": "Italy GP",
    "date": "2026-09-06T13:00Z",
    "status": {"type": {"state": "pre"}},
    "circuit": {"fullName": "Autodromo Nazionale Monza"},
    "competitions": [
        {
            "date": "2026-09-05T14:00Z",
            "type": {"abbreviation": "Qual"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Lando Norris"),
                _competitor(2, "Max Verstappen"),
            ],
        },
        {
            "date": "2026-09-06T13:00Z",
            "type": {"abbreviation": "Race"},
            "status": {"type": {"state": "pre"}},
            "competitors": [
                _competitor(1, "Lando Norris"),
                _competitor(2, "Max Verstappen"),
            ],
        },
    ],
}


# Mid-weekend: ESPN's top-level status mirrors the most recently finished
# session (FP1/FP2 "post"), but the Race is still days away ("pre"). Status
# should be derived from the Race, not the top-level field.
F1_MID_WEEKEND_EVENT = {
    "id": "600057435",
    "name": "Barcelona-Catalunya Grand Prix",
    "shortName": "Barcelona GP",
    "date": "2026-06-14T13:00Z",
    "status": {"type": {"state": "post", "detail": "Final"}},
    "circuit": {"fullName": "Circuit de Barcelona-Catalunya"},
    "competitions": [
        {
            "date": "2026-06-12T11:30Z",
            "type": {"abbreviation": "FP1"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Max Verstappen"),
                _competitor(2, "Charles Leclerc"),
            ],
        },
        {
            "date": "2026-06-12T15:00Z",
            "type": {"abbreviation": "FP2"},
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Max Verstappen"),
                _competitor(2, "Charles Leclerc"),
            ],
        },
        {
            "date": "2026-06-14T13:00Z",
            "type": {"abbreviation": "Race"},
            "status": {"type": {"state": "pre"}},
            "competitors": [
                _competitor(1, "Max Verstappen"),
                _competitor(2, "Charles Leclerc"),
            ],
        },
    ],
}


# NASCAR-style: a single competition with no `type` block.
NASCAR_SCOREBOARD_EVENT = {
    "id": "401700001",
    "name": "Coca-Cola 600",
    "shortName": "Coca-Cola 600",
    "date": "2026-05-25T23:00Z",
    "status": {"type": {"state": "post"}},
    "competitions": [
        {
            "date": "2026-05-25T23:00Z",
            "status": {"type": {"state": "post"}},
            "competitors": [
                _competitor(1, "Kyle Larson", statistics=[{"name": "fastestLap", "value": True}]),
                _competitor(2, "Denny Hamlin"),
            ],
        }
    ],
}


class TestF1MultiSessionWeekend:
    def test_parses_event_metadata(self):
        event = provider._parse_racing_event(F1_SCOREBOARD_EVENT, "f1", "racing")

        assert event is not None
        assert event.id == "600123"
        assert event.name == "Monaco Grand Prix"
        assert event.sport == "racing"
        assert event.league == "f1"
        assert event.circuit_name == "Circuit de Monaco"

    def test_placeholder_team_used_for_home_and_away(self):
        event = provider._parse_racing_event(F1_SCOREBOARD_EVENT, "f1", "racing")

        assert event.home_team is event.away_team
        assert event.home_team.name == "Monaco Grand Prix"

    def test_sessions_parsed_in_order(self):
        event = provider._parse_racing_event(F1_SCOREBOARD_EVENT, "f1", "racing")

        codes = [s.code for s in event.sessions]
        assert codes == ["fp1", "qualifying", "race"]

        names = [s.name for s in event.sessions]
        assert names == ["Practice 1", "Qualifying", "Race"]

    def test_post_race_results_have_finishing_positions(self):
        event = provider._parse_racing_event(F1_SCOREBOARD_EVENT, "f1", "racing")

        race = next(s for s in event.sessions if s.code == "race")
        winner = next(r for r in race.results if r.driver_name == "Max Verstappen")

        assert winner.position == 1
        assert winner.grid_position is None
        assert winner.status == "Finished"
        assert winner.fastest_lap is True
        assert winner.points == 25.0

        second = next(r for r in race.results if r.driver_name == "Charles Leclerc")
        assert second.position == 2
        assert second.fastest_lap is False
        assert second.points == 18.0

    def test_qualifying_results_set_finishing_order(self):
        # A completed qualifying session reports `state="post"`, so its
        # order is recorded as `position` (qualifying result order, which
        # doubles as the race grid order) rather than `grid_position`.
        event = provider._parse_racing_event(F1_SCOREBOARD_EVENT, "f1", "racing")

        quali = next(s for s in event.sessions if s.code == "qualifying")
        pole = next(r for r in quali.results if r.driver_name == "Charles Leclerc")

        assert pole.position == 1
        assert pole.grid_position is None


class TestF1PreRaceWeekend:
    def test_race_session_has_no_finishing_positions_yet(self):
        event = provider._parse_racing_event(F1_PRE_RACE_EVENT, "f1", "racing")

        race = next(s for s in event.sessions if s.code == "race")
        for result in race.results:
            assert result.position is None
            assert result.grid_position is not None
            assert result.status is None

    def test_qualifying_already_finished(self):
        event = provider._parse_racing_event(F1_PRE_RACE_EVENT, "f1", "racing")

        quali = next(s for s in event.sessions if s.code == "qualifying")
        pole = next(r for r in quali.results if r.driver_name == "Lando Norris")
        assert pole.position == 1


class TestF1MidWeekendStatus:
    def test_status_derived_from_race_not_top_level(self):
        # Top-level status is "post"/Final (mirrors finished FP1/FP2), but
        # the Race session is still "pre" - the event should not be final.
        event = provider._parse_racing_event(F1_MID_WEEKEND_EVENT, "f1", "racing")

        assert event.status.state == "scheduled"

    def test_sessions_still_parsed(self):
        event = provider._parse_racing_event(F1_MID_WEEKEND_EVENT, "f1", "racing")

        codes = [s.code for s in event.sessions]
        assert codes == ["fp1", "fp2", "race"]


class TestNASCARSingleSession:
    def test_untyped_competition_becomes_race_session(self):
        event = provider._parse_racing_event(NASCAR_SCOREBOARD_EVENT, "nascar-cup", "racing")

        assert event is not None
        assert len(event.sessions) == 1

        session = event.sessions[0]
        assert session.code == "race"
        assert session.name == "Race"

    def test_finishing_order_and_fastest_lap(self):
        event = provider._parse_racing_event(NASCAR_SCOREBOARD_EVENT, "nascar-cup", "racing")

        session = event.sessions[0]
        winner = next(r for r in session.results if r.driver_name == "Kyle Larson")
        runner_up = next(r for r in session.results if r.driver_name == "Denny Hamlin")

        assert winner.position == 1
        assert winner.fastest_lap is True
        assert runner_up.position == 2
        assert runner_up.fastest_lap is False
