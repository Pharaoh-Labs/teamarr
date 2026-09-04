"""Poll rankings feed TeamStats.rank (#710).

Every rank template variable reads TeamStats.rank, which used to be set from
`team_data.get("rank")` on ESPN's /teams/{id} payload — a field that payload has
never carried for any league, so `{team_rank}`, `{home_team_rank_display}` and
the is_ranked conditions were dead everywhere. Rank now comes from the league's
/rankings polls, fetched once per league and merged into stats at the service.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from teamarr.core.types import TeamStats
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.cache import CACHE_TTL_RANKINGS
from tests.fakes import FakeCache

FRESH = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%MZ")
STALE = (datetime.now(UTC) - timedelta(days=150)).strftime("%Y-%m-%dT%H:%MZ")


def _poll(name: str, poll_type: str, teams: list[tuple[str, int]], updated: str = FRESH):
    return {
        "name": name,
        "type": poll_type,
        "ranks": [
            {"current": rank, "lastUpdated": updated, "team": {"id": team_id}}
            for team_id, rank in teams
        ],
    }


def _provider(payload, league_slug="college-football"):
    client = MagicMock()
    client.get_sport_league.return_value = ("football", league_slug)
    client.get_rankings.return_value = payload
    provider = ESPNProvider(client=client)
    provider._get_sport_league_from_db = lambda league: ("football", league_slug)
    return provider, client


class TestPollParsing:
    def test_ap_poll_maps_team_id_to_rank(self):
        provider, _ = _provider({"rankings": [_poll("AP Top 25", "ap", [("194", 1), ("61", 3)])]})
        assert provider.get_rankings("ncaaf") == {"194": 1, "61": 3}

    def test_ap_wins_over_coaches_poll_regardless_of_payload_order(self):
        payload = {
            "rankings": [
                _poll("AFCA Coaches Poll", "usa", [("61", 4)]),
                _poll("AP Top 25", "ap", [("61", 3)]),
            ]
        }
        provider, _ = _provider(payload)
        assert provider.get_rankings("ncaaf") == {"61": 3}

    def test_fcs_poll_fills_teams_ap_never_covers(self):
        payload = {
            "rankings": [
                _poll("AP Top 25", "ap", [("194", 1)]),
                _poll("FCS Coaches Poll", "fcs", [("147", 1)]),
            ]
        }
        provider, _ = _provider(payload)
        assert provider.get_rankings("ncaaf") == {"194": 1, "147": 1}

    def test_tournament_seedings_are_not_ranks(self):
        payload = {
            "rankings": [
                _poll("NCAA Men's Hockey Tournament Seedings", "tournament", [("41", 1)]),
                _poll("USCHO Men's Poll", "USCHOMENSPOLL", [("77", 2)]),
            ]
        }
        provider, _ = _provider(payload, league_slug="mens-college-hockey")
        assert provider.get_rankings("ncaah") == {"77": 2}

    def test_offseason_poll_is_skipped(self):
        """ESPN serves a season's final poll all offseason — those ranks are gone."""
        payload = {"rankings": [_poll("AP Top 25", "ap", [("194", 1)], updated=STALE)]}
        provider, _ = _provider(payload)
        assert provider.get_rankings("ncaaf") == {}

    def test_ranks_outside_the_top_25_are_dropped(self):
        payload = {"rankings": [_poll("AP Top 25", "ap", [("194", 26), ("61", 0), ("2", 25)])]}
        provider, _ = _provider(payload)
        assert provider.get_rankings("ncaaf") == {"2": 25}

    def test_malformed_entries_do_not_sink_the_poll(self):
        payload = {
            "rankings": [
                "not-a-poll",
                {
                    "name": "AP Top 25",
                    "type": "ap",
                    "ranks": [
                        {"current": "NR", "team": {"id": "1"}, "lastUpdated": FRESH},
                        {"current": 2, "team": {}, "lastUpdated": FRESH},
                        {"current": 3, "team": {"id": "61"}, "lastUpdated": FRESH},
                        None,
                    ],
                },
            ]
        }
        provider, _ = _provider(payload)
        assert provider.get_rankings("ncaaf") == {"61": 3}

    def test_missing_or_error_payload_returns_empty(self):
        for payload in (None, {}, {"rankings": None}, {"code": 404, "message": "no"}):
            provider, _ = _provider(payload)
            assert provider.get_rankings("ncaaf") == {}


class TestLeagueGate:
    def test_pro_league_never_spends_the_call(self):
        """/rankings 404s for every pro league — don't ask."""
        provider, client = _provider({"rankings": []}, league_slug="nfl")
        assert provider.get_rankings("nfl") == {}
        client.get_rankings.assert_not_called()

    def test_ncaa_soccer_is_fetched_despite_its_dotted_slug(self):
        payload = {"rankings": [_poll("United Soccer Coaches", "usa", [("2567", 1)])]}
        provider, client = _provider(payload, league_slug="usa.ncaa.m.1")
        assert provider.get_rankings("usa.ncaa.m.1") == {"2567": 1}
        client.get_rankings.assert_called_once()


class TestServiceEnrichment:
    def _service(self, stats, rankings):
        provider = MagicMock()
        provider.supports_league.return_value = True
        provider.get_team_stats.return_value = stats
        provider.get_rankings.return_value = rankings
        service = SportsDataService(providers=[provider])
        service._cache = FakeCache()
        return service, provider

    def test_rank_is_filled_from_the_league_poll(self):
        service, _ = self._service(TeamStats(record="0-0", wins=0, losses=0), {"194": 4})
        assert service.get_team_stats("194", "ncaaf").rank == 4

    def test_unranked_team_stays_unranked(self):
        service, _ = self._service(TeamStats(record="0-0", wins=0, losses=0), {"194": 4})
        assert service.get_team_stats("57", "ncaaf").rank is None

    def test_provider_supplied_rank_is_not_overwritten(self):
        stats = TeamStats(record="9-1", wins=9, losses=1, rank=2)
        service, provider = self._service(stats, {"194": 4})
        assert service.get_team_stats("194", "ncaaf").rank == 2
        provider.get_rankings.assert_not_called()

    def test_one_poll_fetch_serves_every_team_in_the_league(self):
        service, provider = self._service(TeamStats(record="0-0", wins=0, losses=0), {"194": 4})
        for team_id in ("194", "61", "2483"):
            service.get_team_stats(team_id, "ncaaf")
        assert provider.get_rankings.call_count == 1

    def test_empty_rankings_are_cached_too(self):
        """Leagues with no poll must not re-ask once per team."""
        service, provider = self._service(TeamStats(record="0-0", wins=0, losses=0), {})
        service.get_team_stats("8", "nba")
        service.get_team_stats("9", "nba")
        assert provider.get_rankings.call_count == 1
        assert service._cache.data["rankings:nba"] == {}

    def test_rankings_use_their_own_ttl(self):
        service, _ = self._service(TeamStats(record="0-0", wins=0, losses=0), {"194": 4})
        service.get_team_stats("194", "ncaaf")
        ttls = {key: ttl for key, _, ttl in service._cache.set_calls}
        assert ttls["rankings:ncaaf"] == CACHE_TTL_RANKINGS
