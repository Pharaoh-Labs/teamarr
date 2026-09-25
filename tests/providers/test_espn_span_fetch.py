"""ESPN team-sport scoreboards reject ranged dates (#873)."""

from datetime import date

from teamarr.providers.espn.provider import ESPNProvider


def test_team_sport_span_declines_without_calling_espn():
    class Client:
        def get_scoreboard(self, *args, **kwargs):
            raise AssertionError("ESPN rejects ranged team-sport scoreboards")

    provider = ESPNProvider(client=Client())
    assert provider.get_events_span("nfl", date(2026, 9, 25), date(2026, 9, 27)) is None
