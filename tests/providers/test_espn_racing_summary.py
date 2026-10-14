"""ESPN racing leagues never ask the summary endpoint.

ESPN has no summary for racing (racing/f1 and racing/irl both answer 404),
so the call was a warning per event per run on race weekends and nothing
else. The provider now returns None by sport, like MMA, tennis and cricket.
"""

from unittest.mock import MagicMock

from teamarr.providers.espn.provider import ESPNProvider


def _provider(sport_league):
    client = MagicMock()
    provider = ESPNProvider(client=client)
    provider._get_sport_league_from_db = lambda league: sport_league
    return provider, client


def test_f1_never_calls_the_summary_endpoint():
    provider, client = _provider(("racing", "f1"))
    assert provider.get_event("401778042", "f1") is None
    client.get_event.assert_not_called()


def test_indycar_never_calls_the_summary_endpoint():
    provider, client = _provider(("racing", "irl"))
    assert provider.get_event("401778042", "indycar") is None
    client.get_event.assert_not_called()


def test_a_team_sport_still_asks_for_the_summary():
    provider, client = _provider(("football", "nfl"))
    client.get_event.return_value = {}
    provider.get_event("401", "nfl")
    client.get_event.assert_called_once_with("nfl", "401", ("football", "nfl"))
