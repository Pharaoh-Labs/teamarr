"""Template custom duration must reach every event-channel surface (#946).

A template's game_duration_mode='custom' / game_duration_override used to be
honored only on team channels. `template_to_event_config` dropped the fields
entirely, and every event-path duration derivation (programme stop, racing
race-session window, lifecycle delete threshold) consulted sport/league
defaults only. An 11h template on IMSA produced a 2:45 programme — the
league's sprint fallback — plus a delete threshold that would reap the
channel mid-race.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from teamarr.consumers.event_epg import EventEPGGenerator, EventEPGOptions
from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.consumers.racing_segments import (
    _parse_duration_from_name,
    _session_duration_hours,
    apply_template_race_duration,
)
from teamarr.core.types import Event, EventStatus, RacingSession, Team
from teamarr.database.templates import EventTemplateConfig
from teamarr.services import SportsDataService
from teamarr.utilities.sports import get_effective_duration, template_duration_override

# Race weekend: practice + qualifying Saturday, race Sunday.
FP_START = datetime(2026, 10, 3, 14, 0, tzinfo=UTC)
QUALI_START = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)
RACE_START = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)

CUSTOM_11H = EventTemplateConfig(
    game_duration_mode="custom",
    game_duration_override=11.0,
)
SPORT_MODE = EventTemplateConfig(game_duration_mode="sport")


def _team(tid: str, name: str) -> Team:
    return Team(
        id=tid,
        provider="tsdb",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="imsa",
        sport="racing",
    )


def _racing_event() -> Event:
    return Event(
        id="petit-2026",
        provider="tsdb",
        name="Motul Petit Le Mans",
        short_name="Petit Le Mans",
        start_time=FP_START,
        home_team=_team("1", "IMSA"),
        away_team=_team("2", "Road Atlanta"),
        status=EventStatus(state="pre"),
        league="imsa",
        sport="racing",
        sessions=[
            RacingSession(code="fp1", name="Practice 1", start_time=FP_START),
            RacingSession(code="qualifying", name="Qualifying", start_time=QUALI_START),
            RacingSession(code="race", name="Race", start_time=RACE_START),
        ],
    )


# ===========================================================================
# template_duration_override / get_effective_duration
# ===========================================================================


class TestTemplateDurationOverride:
    def test_dict_template_custom(self):
        assert (
            template_duration_override(
                {"game_duration_mode": "custom", "game_duration_override": 11.0}
            )
            == 11.0
        )

    def test_config_object_custom(self):
        assert template_duration_override(CUSTOM_11H) == 11.0

    def test_sport_mode_has_no_say(self):
        assert template_duration_override(SPORT_MODE) is None
        assert template_duration_override({"game_duration_mode": "sport"}) is None

    def test_custom_without_override_has_no_say(self):
        assert (
            template_duration_override(
                {"game_duration_mode": "custom", "game_duration_override": None}
            )
            is None
        )

    def test_none_template_has_no_say(self):
        assert template_duration_override(None) is None

    def test_effective_duration_accepts_config_object(self):
        durations = {"racing": 3.0}
        assert get_effective_duration("racing", durations, 3.0, CUSTOM_11H) == 11.0
        assert get_effective_duration("racing", durations, 3.0, SPORT_MODE) == 3.0
        assert (
            get_effective_duration(
                "racing", durations, 3.0, EventTemplateConfig(game_duration_mode="default")
            )
            == 3.0
        )

    def test_conversion_preserves_duration_fields(self):
        """template_to_event_config must not drop the duration fields (#946)."""
        from teamarr.database.templates import Template, template_to_event_config

        raw = Template(
            id=1,
            name="IMSA Events",
            template_type="event",
            league="imsa",
            game_duration_mode="custom",
            game_duration_override=11.0,
        )
        config = template_to_event_config(raw)
        assert config.game_duration_mode == "custom"
        assert config.game_duration_override == 11.0
        assert template_duration_override(config) == 11.0


# ===========================================================================
# Race-name duration parsing
# ===========================================================================


class TestNamedRaceDurations:
    def test_petit_le_mans_encodes_ten_hours(self):
        assert _parse_duration_from_name("Motul Petit Le Mans") == 10.0

    def test_twelve_hours_of_sebring_still_parses(self):
        assert _parse_duration_from_name("Mobil 1 Twelve Hours of Sebring") == 12.0

    def test_undated_name_parses_none(self):
        assert _parse_duration_from_name("IMSA Battle on the Bricks") is None

    def test_session_duration_cascade(self):
        # Name parse beats the per-league fallback...
        assert _session_duration_hours("race", None, "imsa", "Motul Petit Le Mans") == 10.0
        # ...which still applies for undated names...
        assert _session_duration_hours("race", None, "imsa", "Sprint Showdown") == 2.75
        # ...and non-race sessions keep their fixed windows.
        assert _session_duration_hours("qualifying", None, "imsa", "Petit Le Mans") == 1.0


# ===========================================================================
# Race-session window adjustment
# ===========================================================================


class TestApplyTemplateRaceDuration:
    def _race_match(self) -> dict:
        return {
            "stream": {"id": 1, "name": "IMSA"},
            "event": _racing_event(),
            "segment": "race",
            "segment_start": RACE_START,
            "segment_end": RACE_START + timedelta(hours=2.75),
        }

    def test_race_segment_stretched_to_override(self):
        match = apply_template_race_duration(self._race_match(), 11.0)
        assert match["segment_end"] == RACE_START + timedelta(hours=11.0)
        assert match["_duration_override"] == 11.0

    def test_non_race_sessions_keep_fixed_windows(self):
        match = self._race_match()
        match.update(
            segment="qualifying",
            segment_start=QUALI_START,
            segment_end=QUALI_START + timedelta(hours=1.0),
        )
        adjusted = apply_template_race_duration(match, 11.0)
        assert adjusted["segment_end"] == QUALI_START + timedelta(hours=1.0)

    def test_no_override_is_a_no_op(self):
        original = self._race_match()
        match = apply_template_race_duration(original, None)
        assert match["segment_end"] == RACE_START + timedelta(hours=2.75)
        assert "_duration_override" not in match


# ===========================================================================
# Lifecycle timing
# ===========================================================================


def _timing_manager() -> ChannelLifecycleManager:
    return ChannelLifecycleManager(
        create_timing="same_day",
        delete_timing="after_event",
        pre_buffer_minutes=60,
        post_buffer_minutes=30,
        default_duration_hours=3.0,
        sport_durations={"racing": 3.0},
    )


class TestEventEndEstimate:
    def test_race_weekend_with_override_ends_at_race_plus_override(self):
        manager = _timing_manager()
        end = manager.get_event_end_time(_racing_event(), 11.0)
        assert end == RACE_START + timedelta(hours=11.0)

    def test_race_weekend_without_override_name_parses_ten_hours(self):
        manager = _timing_manager()
        # No override: the name itself encodes the endurance length.
        end = manager.get_event_end_time(_racing_event())
        assert end == RACE_START + timedelta(hours=10.0)

    def test_race_weekend_without_override_league_fallback(self):
        manager = _timing_manager()
        event = _racing_event()
        object.__setattr__(event, "name", "IMSA Sprint Showdown")
        end = manager.get_event_end_time(event)
        assert end == RACE_START + timedelta(hours=2.75)

    def test_sessionless_event_with_override(self):
        manager = _timing_manager()
        event = _racing_event()
        object.__setattr__(event, "sessions", [])
        end = manager.get_event_end_time(event, 11.0)
        assert end == FP_START + timedelta(hours=11.0)

    def test_non_race_last_session_ignores_override(self):
        manager = _timing_manager()
        event = _racing_event()
        # Weekend ending in qualifying: the override describes the race, so
        # it must not stretch a practice/qualifying-bound end.
        object.__setattr__(
            event,
            "sessions",
            [
                RacingSession(code="fp1", name="Practice 1", start_time=FP_START),
                RacingSession(code="qualifying", name="Qualifying", start_time=QUALI_START),
            ],
        )
        end = manager.get_event_end_time(event, 11.0)
        assert end == QUALI_START + timedelta(hours=1.0)

    def test_delete_time_includes_override_and_buffer(self):
        manager = _timing_manager()
        delete = manager.calculate_delete_time(_racing_event(), 11.0)
        assert delete == RACE_START + timedelta(hours=11.0) + timedelta(minutes=30)

    def test_delete_time_without_override_uses_name_parse(self):
        manager = _timing_manager()
        delete = manager.calculate_delete_time(_racing_event())
        assert delete == RACE_START + timedelta(hours=10.0) + timedelta(minutes=30)


# ===========================================================================
# Programme generation
# ===========================================================================


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    import teamarr.services.league_mappings as lm

    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _options(template: EventTemplateConfig) -> EventEPGOptions:
    return EventEPGOptions(
        template=template,
        pregame_minutes=0,
        sport_durations={"racing": 3.0},
    )


def _generate(match: dict, template: EventTemplateConfig):
    service = SportsDataService(providers=[])
    with (
        patch.object(service, "enrich_event_preview", side_effect=lambda e: e),
        patch.object(service, "get_team_stats", return_value=None),
    ):
        generator = EventEPGGenerator(service)
        programmes, _channels = generator.generate_for_matched_streams([match], _options(template))
    assert len(programmes) == 1
    return programmes[0]


class TestProgrammeDuration:
    def test_standard_path_honors_custom_duration(self):
        # A sessionless racing event takes the standard path.
        event = _racing_event()
        object.__setattr__(event, "sessions", [])
        programme = _generate({"stream": {"id": 1, "name": "IMSA"}, "event": event}, CUSTOM_11H)
        assert programme.stop == FP_START + timedelta(hours=11.0)

    def test_standard_path_sport_mode_unchanged(self):
        event = _racing_event()
        object.__setattr__(event, "sessions", [])
        programme = _generate({"stream": {"id": 1, "name": "IMSA"}, "event": event}, SPORT_MODE)
        assert programme.stop == FP_START + timedelta(hours=3.0)

    def test_race_segment_channel_honors_custom_duration(self):
        match = {
            "stream": {"id": 1, "name": "IMSA"},
            "event": _racing_event(),
            "segment": "race",
            "segment_start": RACE_START,
            "segment_end": RACE_START + timedelta(hours=2.75),
        }
        # The EPG annotation phase (xmltv.py) adjusts race segment ends with
        # the resolved template's duration before programmes are built.
        apply_template_race_duration(match, template_duration_override(CUSTOM_11H))
        programme = _generate(match, CUSTOM_11H)
        assert programme.start == RACE_START
        assert programme.stop == RACE_START + timedelta(hours=11.0)

    def test_qualifying_segment_channel_keeps_session_window(self):
        match = {
            "stream": {"id": 1, "name": "IMSA"},
            "event": _racing_event(),
            "segment": "qualifying",
            "segment_start": QUALI_START,
            "segment_end": QUALI_START + timedelta(hours=1.0),
        }
        apply_template_race_duration(match, template_duration_override(CUSTOM_11H))
        programme = _generate(match, CUSTOM_11H)
        assert programme.stop == QUALI_START + timedelta(hours=1.0)
