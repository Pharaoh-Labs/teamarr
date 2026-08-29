"""Team names survive pipe metadata and apostrophes (#652, #653).

Two independent defects, both in the shared normalization path that every
provider's streams pass through, and both found auditing NCAAF on 2026-08-29
where they accounted for all 22 failures of one source.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from rapidfuzz import fuzz

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.normalizer import (
    extract_and_mask_datetime,
    normalize_for_matching,
)
from teamarr.core.types import Event, EventStatus, Team
from teamarr.utilities.fuzzy_match import normalize_text


def _team(team_id: str, name: str, league: str = "college-football") -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation="",
        league=league,
        sport="football",
    )


def _event(away: str, home: str, league: str = "college-football") -> Event:
    start = datetime.now(UTC) + timedelta(hours=3)
    return Event(
        id="1",
        provider="espn",
        name=f"{away} at {home}",
        short_name=f"{away} at {home}",
        league=league,
        sport="football",
        start_time=start,
        home_team=_team("h", home),
        away_team=_team("a", away),
        status=EventStatus(state="scheduled"),
    )


class TestApostrophesSurviveNormalization:
    """normalize_for_matching and normalize_text run in SEQUENCE, so a
    disagreement between them is unrecoverable downstream (#653)."""

    @pytest.mark.parametrize(
        "text",
        ["Hawai'i", "American Int'l", "G'town Col", "O'Reilly", "Ha'a"],
    )
    def test_both_normalizers_agree(self, text):
        assert normalize_for_matching(text) == normalize_text(text)

    def test_apostrophe_does_not_split_the_token(self):
        assert normalize_for_matching("Hawai'i") == "hawaii"

    def test_curly_apostrophe_normalizes_the_same(self):
        """unidecode runs first via apply_city_translations, so ’ is a
        plain apostrophe by the time the strip happens."""
        assert normalize_for_matching("Hawai’i") == normalize_for_matching("Hawai'i")

    def test_score_against_the_real_team_is_restored(self):
        """46.7 before the fix — under BOTH_TEAMS_THRESHOLD, so the whole
        event was rejected despite a perfectly parsed stream."""
        stream = normalize_text(normalize_for_matching("Hawai'i"))
        assert fuzz.token_set_ratio(stream, normalize_text("Hawai'i Rainbow Warriors")) == 100.0


class TestPipeMetadataIsTrimmed:
    """`_clean_team_name` keeps pipe content expecting the matcher to resolve
    it; no such code existed until #652."""

    def test_classifier_still_hands_over_the_pipe_tail(self):
        """The fix is in the matcher, not the classifier — asserted so the
        fallback is not silently bypassed by a future classifier change."""
        classified = classify_stream(
            "NCAAF 002: ROBERT MORRIS AT WAGNER | 8.29 12:00PM | NEC FRONT ROW"
        )
        assert "|" in (classified.team2 or "")

    def test_leading_segment_is_taken(self):
        from teamarr.consumers.matching.team_matcher import TeamMatcher

        assert TeamMatcher._leading_pipe_segment("WAGNER | 8.29 | NEC FRONT ROW") == "WAGNER"

    def test_too_short_a_head_keeps_the_whole_name(self):
        """Below the 3-char floor the head cannot be a team, so trimming it
        would throw away the only real text."""
        from teamarr.consumers.matching.team_matcher import TeamMatcher

        assert TeamMatcher._leading_pipe_segment("A | Real Madrid") == "A | Real Madrid"

    def test_pipe_fallback_recovers_the_match(self, db_factory):
        from tests.fakes import make_team_matcher

        matcher = make_team_matcher(db_factory=db_factory)
        event = _event("Robert Morris Colonials", "Wagner Seahawks")
        assert matcher._score_teams_against_event("ROBERT MORRIS", "WAGNER", event)
        # The untrimmed form is what the matcher used to be handed, and it
        # scores 57.1 against "Wagner Seahawks" — below the floor.
        assert (
            matcher._score_teams_against_event(
                "ROBERT MORRIS", "WAGNER | 8.29 | NEC FRONT ROW", event
            )
            is None
        )

    def test_venue_suffix_still_matches_on_the_team(self):
        """"Sacramento Kings | Golden 1 Center" — the leading segment is the
        team here too, so the documented pass-through case is unaffected."""
        from teamarr.consumers.matching.team_matcher import TeamMatcher

        assert (
            TeamMatcher._leading_pipe_segment("Sacramento Kings | Golden 1 Center")
            == "Sacramento Kings"
        )


class TestDotSeparatedDates:
    """`8.29` was neither extracted as a date nor removed from the team name."""

    @pytest.mark.parametrize(
        "text,expected",
        [("Game | 8.29 7:00PM |", (8, 29)), ("Game | 08.27 7:00PM |", (8, 27))],
    )
    def test_dot_date_is_extracted(self, text, expected):
        _, parsed, _, _ = extract_and_mask_datetime(text)
        assert parsed is not None
        assert (parsed.month, parsed.day) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Spread 2.5 over",  # one-digit day: a decimal, not a date
            "Game 13.4 rating",  # month out of range
            "Race at 17.45",  # 24h time written with a dot
        ],
    )
    def test_non_dates_are_left_alone(self, text):
        masked, parsed, _, _ = extract_and_mask_datetime(text)
        assert parsed is None
        assert "DATE_MASK" not in masked

    def test_dot_time_with_meridiem_is_not_read_as_a_date(self):
        """The am/pm lookahead is what stops this; how the time itself parses
        is pre-existing behaviour and not asserted here."""
        _, parsed, _, _ = extract_and_mask_datetime("Show at 10.30pm")
        assert parsed is None

    def test_slash_dates_still_win(self):
        """The dot pattern is last, so the established forms are unaffected."""
        _, parsed, _, _ = extract_and_mask_datetime("Event 12/31/25")
        assert (parsed.year, parsed.month, parsed.day) == (2025, 12, 31)
