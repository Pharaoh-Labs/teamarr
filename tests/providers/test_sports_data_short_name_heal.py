"""Self-heal for stale provider_cache rows missing short_name (#201).

Beyond stream_match_cache (covered separately), service.get_events also
reads from a per-(league, date) cache. If those cached event dicts have
home_team.name set but short_name empty, the matcher gets broken events
even after the stream_match_cache rows self-heal — re-caching with the
same broken data.

These tests pin the service-layer self-heal: stale cached lists/dicts
are dropped and the service re-fetches from the provider.
"""

from teamarr.services.sports_data import _event_dict_is_stale, _team_dict_is_stale


class TestTeamDictStaleness:
    def test_populated_team_is_fresh(self):
        assert not _team_dict_is_stale({"name": "Philadelphia Phillies", "short_name": "Phillies"})

    def test_team_with_name_but_no_short_name_is_stale(self):
        assert _team_dict_is_stale({"name": "Philadelphia Phillies", "short_name": ""})

    def test_team_with_name_but_null_short_name_is_stale(self):
        assert _team_dict_is_stale({"name": "Philadelphia Phillies", "short_name": None})

    def test_team_with_name_but_missing_short_name_key_is_stale(self):
        assert _team_dict_is_stale({"name": "Philadelphia Phillies"})

    def test_placeholder_team_is_kept(self):
        # Both empty: placeholder/UFC card scenario, not stale.
        assert not _team_dict_is_stale({"name": "", "short_name": ""})

    def test_none_or_non_dict_is_kept(self):
        assert not _team_dict_is_stale(None)
        assert not _team_dict_is_stale("not a dict")  # type: ignore[arg-type]


class TestEventDictStaleness:
    def test_event_with_fresh_teams_is_fresh(self):
        assert not _event_dict_is_stale(
            {
                "home_team": {"name": "Phillies", "short_name": "Phillies"},
                "away_team": {"name": "Athletics", "short_name": "Athletics"},
            }
        )

    def test_event_with_stale_home_team_is_stale(self):
        assert _event_dict_is_stale(
            {
                "home_team": {"name": "Philadelphia Phillies", "short_name": ""},
                "away_team": {"name": "Athletics", "short_name": "Athletics"},
            }
        )

    def test_event_with_stale_away_team_is_stale(self):
        assert _event_dict_is_stale(
            {
                "home_team": {"name": "Phillies", "short_name": "Phillies"},
                "away_team": {"name": "Athletics", "short_name": ""},
            }
        )
