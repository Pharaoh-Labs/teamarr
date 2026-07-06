"""Regression tests for GH #217 — TSDB season-fallback gating.

The dead `eventsround.php` fallback fired for every league on every empty
date, producing a 404 storm that hung the Event Group preview. The fallback
is now `eventsseason.php`, gated to SEASON_FALLBACK_LEAGUES, so ordinary
leagues (e.g. CFL) with empty individual dates short-circuit to [].
"""

from datetime import date
from unittest.mock import MagicMock

from teamarr.providers.tsdb.provider import TSDBProvider


def _provider_with_empty_day_endpoints():
    """Provider whose day/next endpoints return no events."""
    client = MagicMock()
    client.get_events_by_date.return_value = {"events": []}
    client.get_league_next_events.return_value = {"events": []}
    client.get_events_by_season.return_value = {"events": []}
    return TSDBProvider(client=client), client


def test_non_fallback_league_does_not_hit_season_endpoint():
    """CFL (not in SEASON_FALLBACK_LEAGUES) must short-circuit, never calling
    the full-season endpoint — this is the #217 storm fix."""
    provider, client = _provider_with_empty_day_endpoints()

    events = provider.get_events("cfl", date(2026, 5, 30))

    assert events == []
    client.get_events_by_season.assert_not_called()


def test_fallback_league_uses_season_endpoint():
    """Unrivaled (sparse on day endpoints) still falls back to the season
    endpoint so its coverage is preserved."""
    provider, client = _provider_with_empty_day_endpoints()

    provider.get_events("unrivaled", date(2026, 5, 30))

    client.get_events_by_season.assert_called_once_with("unrivaled")


def test_unrivaled_is_gated():
    assert "unrivaled" in TSDBProvider.SEASON_FALLBACK_LEAGUES
    assert "cfl" not in TSDBProvider.SEASON_FALLBACK_LEAGUES
