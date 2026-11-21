"""Channel kind condition on pinned blocks (#1224).

A block may be limited to managed team channels ('team') or to event channels
('event'), so one league can number its games and its team channels in two
separate bands. The caller states the kind; a caller that states none
satisfies no kind condition. A kind-limited block outranks an unconditioned
block of the same scope rank.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.database import channel_numbers as cn
from teamarr.database import get_db, init_db
from teamarr.database import numbering_exceptions as ne
from teamarr.services.team_channel_manager import TeamChannelManager
from tests.fakes import FakeTeam, make_event

DEFAULT = ne.Lane(id=None, start=1600)
GAMES = 1710
TEAMS = 1750


def _pin(conn, **kw):
    kw.setdefault("scope", "league")
    kw.setdefault("league_code", "nfl")
    kw.setdefault("sport", "football")
    block = ne.add_numbering_exception(conn, **kw)
    assert block is not None
    return block


def _start(conn, **kw):
    return ne.LaneResolver.load(conn, DEFAULT).resolve("football", "nfl", **kw).start


class TestResolution:
    def test_team_only_block(self, db_conn):
        _pin(db_conn, start=TEAMS, channel_kind="team")
        assert _start(db_conn, channel_kind="event") == DEFAULT.start
        assert _start(db_conn, channel_kind="team") == TEAMS

    def test_event_only_block(self, db_conn):
        _pin(db_conn, start=GAMES, channel_kind="event")
        assert _start(db_conn, channel_kind="team") == DEFAULT.start
        assert _start(db_conn, channel_kind="event") == GAMES

    @pytest.mark.parametrize("plain_first", [True, False])
    def test_kind_limited_outranks_unconditioned(self, db_conn, plain_first):
        # Two rows of one league with different starts are allowed, and the
        # winner does not depend on which was added first.
        if plain_first:
            _pin(db_conn, start=GAMES)
            _pin(db_conn, start=TEAMS, channel_kind="team")
        else:
            _pin(db_conn, start=TEAMS, channel_kind="team")
            _pin(db_conn, start=GAMES)
        assert _start(db_conn, channel_kind="event") == GAMES
        assert _start(db_conn, channel_kind="team") == TEAMS

    def test_two_kind_blocks_split_one_league(self, db_conn):
        _pin(db_conn, start=GAMES, channel_kind="event")
        _pin(db_conn, start=TEAMS, channel_kind="team")
        assert _start(db_conn, channel_kind="event") == GAMES
        assert _start(db_conn, channel_kind="team") == TEAMS

    def test_unknown_kind_satisfies_no_condition(self, db_conn):
        _pin(db_conn, start=TEAMS, channel_kind="team")
        _pin(db_conn, start=GAMES, channel_kind="event")
        assert _start(db_conn) == DEFAULT.start
        _pin(db_conn, start=1700)
        assert _start(db_conn) == 1700

    def test_unconditioned_block_takes_both_kinds(self, db_conn):
        _pin(db_conn, start=1700)
        assert _start(db_conn, channel_kind="event") == 1700
        assert _start(db_conn, channel_kind="team") == 1700

    def test_scope_rank_still_dominates(self, db_conn):
        # A sport block limited to team channels does not beat a plain league block.
        _pin(db_conn, start=1700)
        _pin(db_conn, scope="sport", league_code=None, start=1900, channel_kind="team")
        assert _start(db_conn, channel_kind="team") == 1700

    def test_season_ranks_ahead_of_kind(self, db_conn):
        _pin(db_conn, start=900, season_type="postseason")
        _pin(db_conn, start=GAMES, channel_kind="event")
        assert _start(db_conn, season_type="postseason", channel_kind="event") == 900
        assert _start(db_conn, season_type="regular", channel_kind="event") == GAMES

    def test_same_start_is_still_a_conflict(self, db_conn):
        _pin(db_conn, start=GAMES, channel_kind="event")
        with pytest.raises(ne.StartConflict):
            _pin(db_conn, start=GAMES, channel_kind="team")


class TestStorage:
    def test_round_trip_keep_and_clear(self, db_conn):
        block = _pin(db_conn, start=TEAMS, channel_kind=" Team ")
        assert block.channel_kind == "team"
        kept = ne.update_numbering_exception(db_conn, block.id, start=TEAMS + 1)
        assert kept.channel_kind == "team"
        changed = ne.update_numbering_exception(db_conn, block.id, channel_kind="event")
        assert changed.channel_kind == "event"
        cleared = ne.update_numbering_exception(db_conn, block.id, channel_kind=None)
        assert cleared.channel_kind is None
        assert ne.get_numbering_exception(db_conn, block.id).channel_kind is None

    def test_empty_string_means_any(self, db_conn):
        assert _pin(db_conn, start=TEAMS, channel_kind="").channel_kind is None

    def test_invalid_value_is_rejected(self, db_conn):
        assert (
            ne.add_numbering_exception(
                db_conn,
                scope="league",
                league_code="nfl",
                sport="football",
                start=TEAMS,
                channel_kind="both",
            )
            is None
        )
        block = _pin(db_conn, start=TEAMS)
        assert ne.update_numbering_exception(db_conn, block.id, channel_kind="both") is None
        assert ne.get_numbering_exception(db_conn, block.id).channel_kind is None


class TestEventChannelCallers:
    def test_next_number_is_an_event_channel(self, db_conn):
        _pin(db_conn, start=TEAMS, channel_kind="team")
        assert cn.get_next_channel_number(db_conn, "nfl", sport="football") != TEAMS
        _pin(db_conn, start=GAMES, channel_kind="event")
        assert cn.get_next_channel_number(db_conn, "nfl", sport="football") == GAMES

    def test_team_only_block_never_lends_its_group_to_event_channels(self, db_conn, db_factory):
        lifecycle = ChannelLifecycleService(
            db_factory=db_factory,
            sports_service=MagicMock(),
            channel_manager=MagicMock(),
            logo_manager=MagicMock(),
            epg_manager=MagicMock(),
        )
        event = make_event(
            sport="football",
            league="nfl",
            home_team=FakeTeam(name="Home"),
            away_team=FakeTeam(id="2", name="Away"),
        )
        _pin(db_conn, start=TEAMS, channel_kind="team", channel_group_mode="NFL Teams")
        lifecycle._lane_resolver = ne.LaneResolver.load(db_conn, DEFAULT)
        assert lifecycle._pinned_block_group(event) is None
        _pin(db_conn, start=GAMES, channel_kind="event", channel_group_mode="NFL Games")
        lifecycle._lane_resolver = ne.LaneResolver.load(db_conn, DEFAULT)
        assert lifecycle._pinned_block_group(event) == (None, "NFL Games")


class TestTeamChannelAllocation:
    """TeamChannelManager numbers a team channel as kind 'team'."""

    TEAM = {"sport": "football", "primary_league": "nfl", "team_name": "Detroit Lions"}
    SETTINGS = SimpleNamespace(range_start=9000, range_end=None)

    def _allocate(self, conn, occupied=()):
        manager = TeamChannelManager(db_factory=MagicMock(), channel_manager=None)
        number, error = manager._allocate_number(
            None, None, None, set(occupied), self.SETTINGS, conn, self.TEAM
        )
        assert error is None
        return number

    def test_team_only_league_block(self, db_conn):
        _pin(db_conn, start=TEAMS, channel_kind="team")
        assert self._allocate(db_conn) == TEAMS
        assert self._allocate(db_conn, occupied={TEAMS}) == TEAMS + 1

    def test_event_only_league_block_is_skipped(self, db_conn):
        _pin(db_conn, start=GAMES, channel_kind="event")
        assert self._allocate(db_conn) == 9000

    def test_games_and_team_channels_in_two_bands(self, db_conn):
        _pin(db_conn, start=GAMES)
        _pin(db_conn, start=TEAMS, channel_kind="team")
        assert self._allocate(db_conn) == TEAMS
        assert cn.get_next_channel_number(db_conn, "nfl", sport="football") == GAMES

    def test_unconditioned_league_block_still_takes_team_channels(self, db_conn):
        _pin(db_conn, start=GAMES)
        assert self._allocate(db_conn) == GAMES


client = TestClient(app)


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM numbering_exceptions")


class TestApi:
    BASE = "/api/v1/numbering-exceptions"

    def _create(self, **extra):
        body = {"scope": "league", "league_code": "nfl", "start": TEAMS, **extra}
        return client.post(self.BASE, json=body)

    def test_create_list_update_clear(self, api_db):
        resp = self._create(channel_kind="team")
        assert resp.status_code == 200, resp.text
        block = resp.json()
        assert block["channel_kind"] == "team"

        listed = client.get(self.BASE).json()
        assert [b["channel_kind"] for b in listed] == ["team"]

        # Without set_channel_kind an update leaves the condition alone.
        kept = client.put(f"{self.BASE}/{block['id']}", json={"start": TEAMS + 1})
        assert kept.status_code == 200 and kept.json()["channel_kind"] == "team"
        ignored = client.put(f"{self.BASE}/{block['id']}", json={"channel_kind": "event"})
        assert ignored.json()["channel_kind"] == "team"

        changed = client.put(
            f"{self.BASE}/{block['id']}",
            json={"channel_kind": "event", "set_channel_kind": True},
        )
        assert changed.status_code == 200 and changed.json()["channel_kind"] == "event"

        cleared = client.put(
            f"{self.BASE}/{block['id']}",
            json={"channel_kind": None, "set_channel_kind": True},
        )
        assert cleared.status_code == 200 and cleared.json()["channel_kind"] is None

    def test_default_is_all_channels(self, api_db):
        assert self._create().json()["channel_kind"] is None

    def test_invalid_kind_on_create_is_400(self, api_db):
        resp = self._create(channel_kind="both")
        assert resp.status_code == 400, resp.text
        assert "channel kind" in resp.json()["detail"]

    def test_invalid_kind_on_update_is_422(self, api_db):
        block = self._create().json()
        resp = client.put(
            f"{self.BASE}/{block['id']}",
            json={"channel_kind": "both", "set_channel_kind": True},
        )
        assert resp.status_code == 422, resp.text

    def test_preview_names_the_kind(self, api_db):
        self._create(channel_kind="team")
        labels = [lane["label"] for lane in client.get(f"{self.BASE}/preview").json()]
        assert any("team channels" in label for label in labels), labels
