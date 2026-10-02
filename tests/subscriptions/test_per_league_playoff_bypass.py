"""Per-league override of the playoff / All-Star team-filter bypass (#881).

"Include all playoff & All-Star games" was one global switch with a per-source
override. A user following MiLB teams wanted MiLB playoffs left to the team
filter while MLB, NFL and NBA playoffs still bypass it. The override lives on
the per-league config, beside matchup order (#692) and feed separation (#862):
league, then source, then global.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core import SEASON_POSTSEASON, SEASON_REGULAR, Event, EventStatus, Team
from teamarr.database.settings import TeamFilterSettings
from teamarr.database.subscription import (
    get_league_config,
    get_league_playoff_bypass_overrides,
    upsert_league_config,
)
from tests.fakes import FakeGroup

# The user follows one MLB team and one MiLB team.
FOLLOWED = [
    {"provider": "espn", "team_id": "tigers", "league": "mlb"},
    {"provider": "mlbstats", "team_id": "mud-hens", "league": "milb-aaa"},
]


def _team(team_id, league, provider):
    return Team(
        id=team_id,
        provider=provider,
        name=team_id.title(),
        short_name=team_id.title(),
        abbreviation=team_id[:3].upper(),
        league=league,
        sport="baseball",
    )


def _game(event_id, league, home, away, season_type=SEASON_POSTSEASON):
    provider = "espn" if league == "mlb" else "mlbstats"
    return {
        "stream": {"id": hash(event_id) % 10_000, "name": event_id},
        "event": Event(
            id=event_id,
            provider=provider,
            name=f"{away} at {home}",
            short_name=event_id,
            start_time=datetime(2026, 10, 2, 23, tzinfo=UTC),
            home_team=_team(home, league, provider),
            away_team=_team(away, league, provider),
            status=EventStatus(state="scheduled"),
            league=league,
            sport="baseball",
            season_type=season_type,
        ),
    }


# Neither game involves a followed team.
MLB_PLAYOFF = _game("mlb-playoff", "mlb", "yankees", "red-sox")
MILB_PLAYOFF = _game("milb-playoff", "milb-aaa", "bulls", "knights")
MILB_PLAYOFF_FOLLOWED = _game("milb-followed", "milb-aaa", "mud-hens", "knights")
MLB_REGULAR = _game("mlb-regular", "mlb", "yankees", "red-sox", SEASON_REGULAR)


@pytest.fixture
def processor():
    from teamarr.consumers.event_group_processor import EventGroupProcessor

    with patch("teamarr.consumers.event_group_processor.processor.create_default_service"):
        return EventGroupProcessor(db_factory=MagicMock())


def _kept(processor, conn, *, global_bypass, group_bypass=None, games=None):
    settings = TeamFilterSettings(
        enabled=True,
        include_teams=FOLLOWED,
        mode="include",
        bypass_filter_for_playoffs=global_bypass,
    )
    group = FakeGroup(bypass_filter_for_playoffs=group_bypass)
    games = games or [MLB_PLAYOFF, MILB_PLAYOFF, MILB_PLAYOFF_FOLLOWED, MLB_REGULAR]
    with patch("teamarr.database.settings.get_team_filter_settings", return_value=settings):
        kept, _ = processor._filter_by_teams(games, group, conn)
    return [m["event"].id for m in kept]


class TestStorage:
    def test_round_trips_true_false_and_inherit(self, db_conn):
        assert upsert_league_config(db_conn, "milb-aaa").bypass_filter_for_playoffs is None
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=False)
        assert get_league_config(db_conn, "milb-aaa").bypass_filter_for_playoffs is False
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=True)
        assert get_league_config(db_conn, "milb-aaa").bypass_filter_for_playoffs is True

    def test_only_leagues_with_a_choice_are_overrides(self, db_conn):
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=False)
        upsert_league_config(db_conn, "nba", bypass_filter_for_playoffs=True)
        upsert_league_config(db_conn, "nfl", matchup_order="away_first")  # inherits
        overrides = get_league_playoff_bypass_overrides(db_conn)
        assert overrides == {"milb-aaa": False, "nba": True}

    def test_other_overrides_survive_a_playoff_only_change(self, db_conn):
        """The PUT is a full replace, so the UI sends every field; the data
        layer must not drop the playoff choice when another field is saved."""
        upsert_league_config(
            db_conn, "milb-aaa", matchup_order="home_first", bypass_filter_for_playoffs=False
        )
        config = get_league_config(db_conn, "milb-aaa")
        assert (config.matchup_order, config.bypass_filter_for_playoffs) == ("home_first", False)


class TestFilter:
    def test_the_request_milb_playoffs_filtered_mlb_playoffs_kept(self, processor, db_conn):
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=False)

        kept = _kept(processor, db_conn, global_bypass=True)

        # MLB playoff bypasses the filter; the MiLB one is left to it, so only
        # the followed team's playoff game survives.
        assert kept == ["mlb-playoff", "milb-followed"]

    def test_without_an_override_the_global_switch_applies_to_every_league(
        self, processor, db_conn
    ):
        assert _kept(processor, db_conn, global_bypass=True) == [
            "mlb-playoff",
            "milb-playoff",
            "milb-followed",
        ]
        assert _kept(processor, db_conn, global_bypass=False) == ["milb-followed"]

    def test_a_league_can_opt_in_while_the_global_switch_is_off(self, processor, db_conn):
        upsert_league_config(db_conn, "mlb", bypass_filter_for_playoffs=True)
        assert _kept(processor, db_conn, global_bypass=False) == ["mlb-playoff", "milb-followed"]

    def test_league_outranks_the_source_switch(self, processor, db_conn):
        """A source with the bypass on must not re-include a league the user
        switched off, and one with it off must not hide a league they opted in."""
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=False)
        assert _kept(processor, db_conn, global_bypass=False, group_bypass=True) == [
            "mlb-playoff",
            "milb-followed",
        ]
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=True)
        assert _kept(processor, db_conn, global_bypass=True, group_bypass=False) == [
            "milb-playoff",
            "milb-followed",
        ]

    def test_regular_season_games_are_never_bypassed(self, processor, db_conn):
        upsert_league_config(db_conn, "mlb", bypass_filter_for_playoffs=True)
        assert _kept(processor, db_conn, global_bypass=True, games=[MLB_REGULAR]) == []

    def test_master_toggle_off_still_filters_nothing(self, processor, db_conn):
        upsert_league_config(db_conn, "milb-aaa", bypass_filter_for_playoffs=False)
        settings = TeamFilterSettings(enabled=False, include_teams=FOLLOWED)
        with patch("teamarr.database.settings.get_team_filter_settings", return_value=settings):
            kept, filtered = processor._filter_by_teams(
                [MLB_PLAYOFF, MILB_PLAYOFF], FakeGroup(), db_conn
            )
        assert len(kept) == 2 and filtered == 0


class TestApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from teamarr.api.app import app
        from teamarr.database.connection import init_db

        path = tmp_path / "test.db"
        init_db(path)
        monkeypatch.setenv("DATABASE_PATH", str(path))
        return TestClient(app)

    def test_put_and_list_carry_the_override(self, client):
        resp = client.put(
            "/api/v1/league-configs/milb-aaa", json={"bypass_filter_for_playoffs": False}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["bypass_filter_for_playoffs"] is False

        listed = client.get("/api/v1/league-configs").json()["configs"]
        assert [(c["league_code"], c["bypass_filter_for_playoffs"]) for c in listed] == [
            ("milb-aaa", False)
        ]

    def test_leaving_it_out_means_inherit(self, client):
        resp = client.put("/api/v1/league-configs/nfl", json={"matchup_order": "away_first"})
        assert resp.json()["bypass_filter_for_playoffs"] is None
