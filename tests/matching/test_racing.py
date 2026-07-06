"""Racing pipeline tests: classification, matcher scoring, session durations.

Racing leagues are configured with ``event_type='event'`` and have no reliable
text keyword, so a stream is classified ``RACING_EVENT`` purely because the
group is racing-dominant and the stream has no team pattern. This is the
regression-prone path (cf. #157): a team-sport stream that leaks into a
racing-dominant group must NOT be hijacked as a race.
"""

from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.racing_matcher import RacingMatchContext, RacingMatcher
from teamarr.consumers.racing_segments import (
    _parse_duration_from_name,
    _session_duration_hours,
)
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    DetectionKeywordService.invalidate_cache()


# ---------------------------------------------------------------------------
# Classification: genuine racing streams classify as RACING_EVENT
# ---------------------------------------------------------------------------


def test_f1_stream_classifies_racing():
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT
    assert c.event_hint  # full text carried for fuzzy matching


def test_nascar_stream_classifies_racing():
    c = classify_stream("NASCAR Cup Series - Daytona 500", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_nascar_espn_at_city_format_classifies_racing():
    # ESPN names NASCAR events "[Series] at [City]" — the "at" must not trigger
    # team extraction since "NASCAR Cup Series" is a series name, not a team abbrev.
    c = classify_stream("NASCAR Cup Series at San Diego", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_nascar_orap_at_city_format_classifies_racing():
    c = classify_stream("NASCAR O'Reilly Auto Parts Series at San Diego", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_racing_only_applies_for_event_league_type():
    # Same name, but a non-racing (team) group must not route to racing.
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="team")
    assert c.category != StreamCategory.RACING_EVENT


# ---------------------------------------------------------------------------
# Classification: leaked team-sport streams in a racing-dominant group are
# NOT hijacked
# ---------------------------------------------------------------------------


def test_team_stream_with_separator_falls_through():
    # "SD at BAL" has a game separator → team matching, not racing.
    c = classify_stream("SD at BAL", league_event_type="event")
    assert c.category == StreamCategory.TEAM_VS_TEAM


def test_team_stream_with_nonracing_sport_hint_falls_through():
    # No separator, but a positive non-racing sport hint ("Ice Hockey") vetoes
    # racing classification — the #242 follow-up guard.
    c = classify_stream("NHL | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT


def test_hockey_single_team_in_racing_group_is_not_racing():
    c = classify_stream("US | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT


def test_racing_league_hints_cover_all_schema_racing_leagues():
    """_RACING_LEAGUE_HINTS is a hardcoded mirror of the racing leagues seeded in
    schema.sql (the classifier is a pure text module with no DB access). This test
    is the sync contract: add a racing league to the schema and it fails until the
    frozenset learns the new code."""
    import re
    from pathlib import Path

    from teamarr.consumers.matching.classifier import _RACING_LEAGUE_HINTS

    schema = Path("teamarr/database/schema.sql").read_text(encoding="utf-8")
    schema_racing_codes = {
        m.group(1)
        for m in re.finditer(r"^\s*\('([a-z0-9-]+)',[^)\n]*'racing'", schema, re.MULTILINE)
    }
    assert schema_racing_codes, "failed to parse racing leagues from schema.sql"
    missing = schema_racing_codes - _RACING_LEAGUE_HINTS
    assert not missing, f"racing leagues in schema.sql missing from _RACING_LEAGUE_HINTS: {missing}"


# ---------------------------------------------------------------------------
# RacingMatcher venue-country scoring (take-and-fix of PR #263)
#
# venue.country is deliberately NOT a peer fuzzy candidate: token_set_ratio
# scores a bare country subset at 100, so a country hit must never outrank a
# real name/circuit match on a different event. It contributes only:
# - to the single-covering-event sanity check (no ambiguity to create), and
# - as a fallback when it identifies exactly ONE covering event.
# ---------------------------------------------------------------------------


def _event(eid, name, circuit=None, country=None):
    return SimpleNamespace(
        id=eid,
        name=name,
        short_name=name,
        circuit_name=circuit,
        venue=SimpleNamespace(country=country) if country else None,
        league="nascar-cup",
    )


def _ctx(stream_name):
    return RacingMatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 14),
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=None,
    )


def _matcher():
    return RacingMatcher(service=None, cache=None)


def test_name_match_beats_country_on_other_event():
    # Doubleheader window: the stream names race A; race B shares no name tokens
    # but its venue country appears in the stream. A must win.
    a = _event("a", "Viva Mexico 250", circuit="Autodromo Hermanos Rodriguez", country="Mexico")
    b = _event("b", "Firekeepers Casino 400", circuit="Michigan Intl Speedway", country="USA")
    out = _matcher()._match_to_event(_ctx("NASCAR Cup: Viva Mexico 250"), [a, b], "nascar-cup")
    assert out.is_matched and out.event.id == "a"


def test_unique_country_fallback_matches():
    # "at Mexico City" carries no event-name tokens, but only one covering
    # event is in Mexico → country fallback resolves it.
    a = _event("a", "Viva Mexico 250", country="Mexico")
    b = _event("b", "Firekeepers Casino 400", country="USA")
    out = _matcher()._match_to_event(
        _ctx("NASCAR Cup Series at Mexico"), [a, b], "nascar-cup"
    )
    assert out.is_matched and out.event.id == "a"


def test_ambiguous_country_does_not_match():
    # Two covering events in the same country: a bare country reference must
    # stay unmatched rather than guess.
    a = _event("a", "Race One GP", country="USA")
    b = _event("b", "Race Two GP", country="USA")
    out = _matcher()._match_to_event(_ctx("Cup Series live from USA"), [a, b], "nascar-cup")
    assert not out.is_matched


def test_single_event_country_passes_sanity_check():
    # One covering event whose name shares nothing with the stream, but the
    # stream names the venue country → sanity check passes via country score.
    a = _event("a", "Viva 250", country="Mexico")
    out = _matcher()._match_to_event(_ctx("NASCAR at Mexico"), [a], "nascar-cup")
    assert out.is_matched and out.event.id == "a"


# ---------------------------------------------------------------------------
# Racing session duration resolution (teamarr/consumers/racing_segments.py)
#
# `_parse_duration_from_name` and `_session_duration_hours` for endurance races
# (WEC/IMSA) whose race length varies far more than the global "racing" sport
# default allows.
# ---------------------------------------------------------------------------


class TestParseDurationFromName:
    def test_digit_hours(self):
        assert _parse_duration_from_name("24 Hours of Le Mans") == 24.0
        assert _parse_duration_from_name("6 Hours of Spa-Francorchamps") == 6.0

    def test_word_number_hours(self):
        assert _parse_duration_from_name("Mobil 1 Twelve Hours of Sebring") == 12.0

    def test_no_duration_in_name(self):
        assert _parse_duration_from_name("Rolex 24 At Daytona") is None
        assert _parse_duration_from_name("Petit Le Mans") is None
        assert _parse_duration_from_name("Battle on the Bricks") is None

    def test_none_name(self):
        assert _parse_duration_from_name(None) is None


class TestSessionDurationHours:
    def test_non_race_sessions_unaffected(self):
        assert _session_duration_hours("fp1", {}, "wec", "24 Hours of Le Mans") == 1.0
        assert _session_duration_hours("qualifying", {}, "imsa", "Petit Le Mans") == 1.0

    def test_explicit_name_duration_wins(self):
        assert _session_duration_hours("race", {}, "wec", "24 Hours of Le Mans") == 24.0
        twelve = _session_duration_hours("race", {}, "imsa", "Mobil 1 Twelve Hours of Sebring")
        assert twelve == 12.0

    def test_league_fallback_when_name_has_no_duration(self):
        assert _session_duration_hours("race", {}, "wec", "Petit Le Mans") == 6.0
        assert _session_duration_hours("race", {}, "imsa", "Battle on the Bricks") == 2.75

    def test_sport_default_for_other_leagues(self):
        assert _session_duration_hours("race", {"racing": 3.0}, "f1", "Monaco Grand Prix") == 3.0

    def test_sport_default_when_no_league(self):
        assert _session_duration_hours("race", {"racing": 3.0}) == 3.0
