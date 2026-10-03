"""Per-league override of the channel creation window (#851).

Creation timing was one global setting, so a window wide enough for weekly
sports (NFL three days out) also created three days of daily sports (MLB).
The override lives on the per-league config, beside matchup order (#692) and
feed separation (#862): a league with a timing of its own uses it, every
other league follows the global setting. Deletion stays global.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.consumers.matching.result import ExcludedReason
from teamarr.core import Event, EventStatus, Team
from teamarr.database.connection import get_db, init_db
from teamarr.database.subscription import (
    get_league_config,
    get_league_create_timing_overrides,
    upsert_league_config,
)

# Sunday 1pm ET kickoff / first pitch, seen from Thursday evening.
GAME_START = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
THURSDAY = datetime(2026, 10, 8, 22, 0, tzinfo=UTC)
SUNDAY_MORNING = datetime(2026, 10, 11, 0, 1, tzinfo=UTC)


def _game(league: str, sport: str) -> Event:
    def team(team_id: str) -> Team:
        return Team(
            id=team_id,
            provider="espn",
            name=team_id.title(),
            short_name=team_id.title(),
            abbreviation=team_id[:3].upper(),
            league=league,
            sport=sport,
        )

    return Event(
        id=f"{league}-game",
        provider="espn",
        name="Away at Home",
        short_name="AWY @ HOM",
        start_time=GAME_START,
        home_team=team("home"),
        away_team=team("away"),
        status=EventStatus(state="scheduled"),
        league=league,
        sport=sport,
    )


NFL = _game("nfl", "football")
MLB = _game("mlb", "baseball")


@pytest.fixture(autouse=True)
def _utc_user(monkeypatch):
    monkeypatch.setattr("teamarr.utilities.tz.get_user_timezone", lambda: ZoneInfo("UTC"))


def _freeze_now(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("teamarr.consumers.lifecycle.timing.now_user", lambda: now)


class TestTiming:
    def test_a_league_can_open_days_early_while_the_rest_stay_same_day(self, monkeypatch):
        manager = ChannelLifecycleManager(
            create_timing="same_day",
            league_create_overrides={"nfl": ("before_event", 72 * 60)},
        )
        _freeze_now(monkeypatch, THURSDAY)

        assert manager.should_create_channel(NFL).should_act
        assert not manager.should_create_channel(MLB).should_act
        # The exclusion verdict the run reports follows the same window
        assert manager.categorize_event_timing(NFL) is None
        assert manager.categorize_event_timing(MLB) is ExcludedReason.BEFORE_WINDOW

    def test_a_league_can_stay_same_day_under_a_wide_global_window(self, monkeypatch):
        manager = ChannelLifecycleManager(
            create_timing="before_event",
            pre_buffer_minutes=72 * 60,
            league_create_overrides={"mlb": ("same_day", None)},
        )
        _freeze_now(monkeypatch, THURSDAY)

        assert manager.should_create_channel(NFL).should_act
        assert not manager.should_create_channel(MLB).should_act

        _freeze_now(monkeypatch, SUNDAY_MORNING)
        assert manager.should_create_channel(MLB).should_act

    def test_before_event_without_a_buffer_uses_the_global_buffer(self, monkeypatch):
        manager = ChannelLifecycleManager(
            create_timing="same_day",
            pre_buffer_minutes=72 * 60,
            league_create_overrides={"nfl": ("before_event", None)},
        )
        _freeze_now(monkeypatch, THURSDAY)

        assert manager.should_create_channel(NFL).should_act

    def test_a_zero_buffer_is_an_override_not_a_missing_one(self, monkeypatch):
        manager = ChannelLifecycleManager(
            create_timing="same_day",
            pre_buffer_minutes=72 * 60,
            league_create_overrides={"nfl": ("before_event", 0)},
        )
        _freeze_now(monkeypatch, datetime(2026, 10, 11, 16, 0, tzinfo=UTC))  # 1h before

        assert not manager.should_create_channel(NFL).should_act

    def test_the_override_does_not_move_the_delete_threshold(self):
        plain = ChannelLifecycleManager(create_timing="same_day")
        overridden = ChannelLifecycleManager(
            create_timing="same_day",
            league_create_overrides={"nfl": ("before_event", 72 * 60)},
        )

        assert overridden.calculate_delete_time(NFL) == plain.calculate_delete_time(NFL)


class TestStorage:
    @pytest.fixture
    def conn(self, tmp_path, monkeypatch):
        path = tmp_path / "test.db"
        init_db(path)
        monkeypatch.setenv("DATABASE_PATH", str(path))
        with get_db() as connection:
            yield connection

    def test_only_leagues_with_a_timing_are_overrides(self, conn):
        upsert_league_config(
            conn, "nfl", channel_create_timing="before_event", channel_pre_buffer_minutes=4320
        )
        upsert_league_config(conn, "mlb", matchup_order="away_first")

        assert get_league_create_timing_overrides(conn) == {"nfl": ("before_event", 4320)}

    def test_a_buffer_is_dropped_unless_the_timing_is_before_event(self, conn):
        upsert_league_config(
            conn, "mlb", channel_create_timing="same_day", channel_pre_buffer_minutes=4320
        )
        upsert_league_config(conn, "nhl", channel_pre_buffer_minutes=4320)

        assert get_league_config(conn, "mlb").channel_pre_buffer_minutes is None
        assert get_league_config(conn, "nhl").channel_pre_buffer_minutes is None
        assert get_league_create_timing_overrides(conn) == {"mlb": ("same_day", None)}


class TestApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from teamarr.api.app import app

        path = tmp_path / "test.db"
        init_db(path)
        monkeypatch.setenv("DATABASE_PATH", str(path))
        return TestClient(app)

    def test_put_and_list_carry_the_override(self, client):
        resp = client.put(
            "/api/v1/league-configs/nfl",
            json={"channel_create_timing": "before_event", "channel_pre_buffer_minutes": 4320},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["channel_create_timing"] == "before_event"
        assert resp.json()["channel_pre_buffer_minutes"] == 4320

        listed = client.get("/api/v1/league-configs").json()["configs"]
        assert [
            (c["league_code"], c["channel_create_timing"], c["channel_pre_buffer_minutes"])
            for c in listed
        ] == [("nfl", "before_event", 4320)]

    def test_leaving_it_out_means_inherit(self, client):
        resp = client.put("/api/v1/league-configs/nfl", json={"matchup_order": "away_first"})
        assert resp.json()["channel_create_timing"] is None
        assert resp.json()["channel_pre_buffer_minutes"] is None

    @pytest.mark.parametrize(
        "body",
        [
            {"channel_create_timing": "next_week"},
            {"channel_create_timing": "before_event", "channel_pre_buffer_minutes": -1},
            {"channel_create_timing": "before_event", "channel_pre_buffer_minutes": 20161},
        ],
    )
    def test_invalid_values_are_rejected(self, client, body):
        assert client.put("/api/v1/league-configs/nfl", json=body).status_code == 400
