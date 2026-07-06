"""Tests for the {league_abbrev} construction rule."""

import pytest

from teamarr.templates.variables.identity import construct_league_abbrev


@pytest.mark.parametrize(
    "name,expected",
    [
        ("NBA", "NBA"),  # already all-caps passes through
        ("World Cup", "WC"),  # first letter of each word
        ("Premier League", "PL"),
        ("La Liga", "LL"),
        ("Serie A", "SA"),
        ("UEFA Champions League", "UEFACL"),  # caps + word starts
        ("NCAA Men's Basketball", "NCAAMB"),  # apostrophe isn't a word boundary
        ("Big Bash League", "BBL"),
        ("F1", "F1"),  # digits kept
        ("Top 14", "T14"),
        ("United Rugby Championship", "URC"),
        ("", ""),
    ],
)
def test_construct_league_abbrev(name, expected):
    assert construct_league_abbrev(name) == expected
