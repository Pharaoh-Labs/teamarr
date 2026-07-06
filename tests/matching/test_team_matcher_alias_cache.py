"""Country-resolution memoization + log de-duplication in TeamMatcher (#256).

The same stream team names are checked against every candidate event, so the
country resolution (and its `[ALIAS]` debug log) must run once per unique name,
not once per candidate. Self-maps (a name that resolves to itself) carry no
signal and must not log.
"""

import logging
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.matching.team_matcher import TeamMatcher


@pytest.fixture
def matcher():
    # db_factory=None → no user aliases; service/cache unused by _resolve_alias.
    return TeamMatcher(service=MagicMock(), cache=MagicMock(), db_factory=None)


def test_abbreviation_resolves_via_alias(matcher):
    # The actual #256 bug: spaced/punctuated abbreviation now resolves natively.
    assert matcher._resolve_alias("EE. UU.", None) == "united states"


def test_country_resolution_is_memoized(matcher):
    spy = MagicMock(wraps=matcher._country_resolver.resolve)
    matcher._country_resolver.resolve = spy

    for _ in range(5):
        matcher._resolve_alias("EE. UU.", None)

    # Resolved once; the other four calls hit the per-name cache.
    assert spy.call_count == 1


def test_alias_log_fires_once_per_name(matcher, caplog):
    with caplog.at_level(logging.DEBUG, logger="teamarr.consumers.matching.team_matcher"):
        for _ in range(10):
            matcher._resolve_alias("EE. UU.", None)

    alias_lines = [r for r in caplog.records if "Country name resolved" in r.message]
    assert len(alias_lines) == 1


def test_self_map_does_not_log(matcher, caplog):
    # "Australia" resolves to itself — no translation happened, so no log.
    with caplog.at_level(logging.DEBUG, logger="teamarr.consumers.matching.team_matcher"):
        matcher._resolve_alias("Australia", None)

    assert matcher._resolve_alias("Australia", None) == "australia"
    alias_lines = [r for r in caplog.records if "Country name resolved" in r.message]
    assert alias_lines == []
