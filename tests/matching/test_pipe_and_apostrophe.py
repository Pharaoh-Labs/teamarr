"""Team names survive pipe metadata and apostrophes (#652, #653).

Two independent defects, both in the shared normalization path that every
provider's streams pass through, and both found auditing NCAAF on 2026-08-29
where they accounted for all 22 failures of one source.

A dot-separated date pattern (8.29) was proposed here and withdrawn: UK
listings write kickoff times the same way, so "Arsenal v Chelsea 7.30" read as
30 July. Built-in masks are extracted_date_trusted=True and the trusted-date
gate rejects candidates more than a day out, which would have turned correct
matches into DATE_MISMATCH. It was never load-bearing anyway -- with the date
fully extracted, team2 still scores 57.1; the pipe fallback alone is the fix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from rapidfuzz import fuzz

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.normalizer import normalize_for_matching
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
