"""PFL and LFA classify and route like UFC (#756).

Adding promotions to an event-card path that had only ever seen UFC exposes
two failure modes worth pinning: the promotion token has to reach the league
hint (PFL cards are named by city as often as by number, so "PFL Dubai" must
still say "pfl"), and it has to be stripped before the fuzzy event-name
fallback scores — every candidate card carries it, so leaving it in scores
~100 against an arbitrary card on the date.
"""

from datetime import UTC

import pytest

from teamarr.consumers.matching.classifier import (
    StreamCategory,
    classify_stream,
    detect_league_hint,
    extract_event_card_hint,
)
from teamarr.consumers.mma_segments import is_mma_event
from teamarr.core import Event, EventStatus, Team


class TestLeagueHints:
    @pytest.mark.parametrize(
        "stream,league",
        [
            ("PFL Dubai: Nurmagomedov vs. Davis", "pfl"),
            ("PFL 5: Main Card", "pfl"),
            ("US: PFL Chicago (Prelims)", "pfl"),
            ("Professional Fighters League - Prelims", "pfl"),
            ("LFA 235: Stewart vs. Havener", "lfa"),
            ("Legacy Fighting Alliance 230", "lfa"),
            ("UFC 335: Prelims", "ufc"),
        ],
    )
    def test_promotion_token_resolves_to_its_league(self, stream, league):
        assert detect_league_hint(stream) == league

    def test_city_named_card_still_classifies_as_event_card(self):
        """PFL names cards by city, so there is no number to key on."""
        classified = classify_stream("PFL Dubai: Nurmagomedov vs. Davis")

        assert classified.category == StreamCategory.EVENT_CARD
        assert classified.league_hint == "pfl"
        assert classified.team1 == "Nurmagomedov"
        assert classified.team2 == "Davis"

    def test_numbered_card_yields_an_event_hint(self):
        assert extract_event_card_hint("LFA 235: Stewart vs. Havener") == "LFA 235"
        assert extract_event_card_hint("PFL 5: Main Card") == "PFL 5"

    def test_segments_are_detected_on_non_ufc_cards(self):
        assert classify_stream("PFL 5: Main Card").card_segment == "main_card"
        assert classify_stream("PFL Chicago: Pettis vs. McKee (Prelims)").card_segment == "prelims"


def _event(league: str, sport: str = "mma") -> Event:
    from datetime import datetime

    team = Team(
        id="1",
        provider="espn",
        name="Fighter A",
        short_name="A",
        abbreviation="A",
        league=league,
        sport=sport,
    )
    return Event(
        id="1",
        provider="espn",
        name="Card",
        short_name="Card",
        start_time=datetime(2026, 2, 7, 17, tzinfo=UTC),
        status=EventStatus(state="scheduled"),
        home_team=team,
        away_team=team,
        league=league,
        sport=sport,
    )


class TestSegmentExpansionScope:
    """Segment handling is keyed on sport so every promotion gets it (#756)."""

    @pytest.mark.parametrize("league", ["ufc", "pfl", "lfa"])
    def test_every_mma_promotion_gets_segment_handling(self, league):
        assert is_mma_event(_event(league)) is True

    def test_boxing_is_not_segmented(self):
        """Boxing cards carry no ESPN segment times, so they stay whole."""
        assert is_mma_event(_event("boxing", sport="boxing")) is False

    def test_none_is_not_segmented(self):
        assert is_mma_event(None) is False


class TestPromotionTokenStripping:
    """The promotion token must not survive into fuzzy event-name scoring."""

    @pytest.mark.parametrize(
        "stream,expected",
        [
            ("PFL Dubai Prelims", "dubai"),
            ("LFA 235 Main Card", "235"),
            ("UFC at the White House", "at the white house"),
        ],
    )
    def test_noise_strip_leaves_only_the_distinctive_part(self, stream, expected):
        import re

        from teamarr.utilities.fuzzy_match import normalize_text

        cleaned = re.sub(
            r"\b(ufc|pfl|lfa|bellator|mma|boxing|prelims|main card|early prelims"
            r"|live|event|ppv|pm|am|et|pt|ct|mt)\b",
            "",
            normalize_text(stream),
        ).strip()

        assert " ".join(cleaned.split()) == expected
