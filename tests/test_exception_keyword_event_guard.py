# ruff: noqa: E501  — captured stream names are the fixtures
"""Exception keywords never fire on a word the matched event is named with (#803).

Prod, 2026-09-12: the seeded "Spanish" keyword, set to Ignore, dropped all 12
matched Spanish Grand Prix streams at channel creation.
"""

from __future__ import annotations

from dataclasses import dataclass

from teamarr.database.channels.keywords import check_exception_keyword, event_identity_text
from teamarr.database.exception_keywords import ExceptionKeyword

LANGUAGES = [
    ExceptionKeyword(
        id=1, label="Spanish", match_terms="Spanish, En Español, (ESP), Español", behavior="ignore"
    ),
    ExceptionKeyword(
        id=2, label="French", match_terms="French, (FRA), Français", behavior="ignore"
    ),
    ExceptionKeyword(
        id=3, label="Italian", match_terms="Italian, (ITA), Italiano", behavior="ignore"
    ),
]


@dataclass
class _Venue:
    country: str | None


@dataclass
class _Event:
    name: str
    short_name: str | None = None
    venue: _Venue | None = None


@dataclass
class _ChannelRow:
    event_name: str | None


SPANISH_GP = _Event("Tag Heuer Spanish Grand Prix", "Spanish GP", _Venue("Spain"))


class TestEventIdentityText:
    def test_event_fields(self):
        assert (
            event_identity_text(SPANISH_GP) == "Tag Heuer Spanish Grand Prix | Spanish GP | Spain"
        )

    def test_channel_row_only_has_the_name(self):
        assert (
            event_identity_text(_ChannelRow("Pirelli Italian Grand Prix"))
            == "Pirelli Italian Grand Prix"
        )

    def test_none_and_str(self):
        assert event_identity_text(None) == ""
        assert event_identity_text("French Open") == "French Open"


class TestGuard:
    def test_spanish_grand_prix_streams_survive_the_spanish_keyword(self):
        stream = "TSN+ 07: Formula 1 On-Board Camera: Charles Leclerc - Spanish Grand Prix Practice #3 @ 12 Sep 06:20 AM ET"
        assert check_exception_keyword(stream, LANGUAGES, event_identity_text(SPANISH_GP)) == (
            None,
            None,
        )

    def test_a_real_spanish_language_feed_of_the_spanish_gp_still_fires(self):
        stream = "ESPN+ 41: En Español - Spanish Grand Prix Qualifying @ 12 Sep 10:00AM ET"
        assert check_exception_keyword(stream, LANGUAGES, event_identity_text(SPANISH_GP)) == (
            "Spanish",
            "ignore",
        )
        stream = "F1: Spanish Grand Prix Race (ESP) [1080p]"
        assert check_exception_keyword(stream, LANGUAGES, event_identity_text(SPANISH_GP)) == (
            "Spanish",
            "ignore",
        )

    def test_french_open_and_italian_gp(self):
        assert check_exception_keyword(
            "Tennis: French Open - Court Philippe-Chatrier", LANGUAGES, "French Open"
        ) == (None, None)
        assert check_exception_keyword(
            "F1 TV 03: Italian Grand Prix - F1 Race", LANGUAGES, "Pirelli Italian Grand Prix"
        ) == (None, None)

    def test_without_event_text_behaviour_is_unchanged(self):
        stream = "F1 TV 03: Italian Grand Prix - F1 Race"
        assert check_exception_keyword(stream, LANGUAGES) == ("Italian", "ignore")

    def test_other_events_are_not_shielded(self):
        # The guard is per event: a Spanish-language NBA feed still fires.
        assert check_exception_keyword(
            "NBA: Lakers vs Celtics (Spanish)", LANGUAGES, "Los Angeles Lakers at Boston Celtics"
        ) == ("Spanish", "ignore")

    def test_enforcement_sees_the_channel_row_name(self):
        row = _ChannelRow("Tag Heuer Spanish Grand Prix")
        stream = "TSN+ 05: Formula 1 Driver Tracker - Spanish Grand Prix Practice #3"
        assert check_exception_keyword(stream, LANGUAGES, event_identity_text(row)) == (None, None)
