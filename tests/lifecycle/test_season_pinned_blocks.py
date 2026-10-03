"""Season-aware pinned blocks (#950).

A pinned block may be limited to one season type and may name the channel
group its channels go to: "NBA postseason at 900, in 09 TEAMARR {league}",
with regular-season NBA numbering from the default lane. Before this a league
pin applied to every game of the league, so moving playoffs into a priority
block meant deleting and re-creating pins twice a year per league.
"""

from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.database import channel_numbers as cn
from teamarr.database import numbering_exceptions as ne
from teamarr.database.channels import create_managed_channel, get_managed_channel
from teamarr.database.groups import create_group
from tests.fakes import FakeManagedChannel, FakeTeam, make_event

DEFAULT = ne.Lane(id=None, start=1600)


def _pin(conn, **kw):
    kw.setdefault("scope", "league")
    kw.setdefault("league_code", "nba")
    kw.setdefault("sport", "basketball")
    block = ne.add_numbering_exception(conn, **kw)
    assert block is not None
    return block


def _resolver(conn):
    return ne.LaneResolver.load(conn, DEFAULT)


class TestSeasonCondition:
    def test_conditioned_pin_takes_only_its_season(self, db_conn):
        _pin(db_conn, start=900, season_type="postseason")
        r = _resolver(db_conn)
        assert r.resolve("basketball", "nba", season_type="postseason").start == 900
        assert r.resolve("basketball", "nba", season_type="regular") is DEFAULT
        assert r.resolve("basketball", "nba", season_type="preseason") is DEFAULT

    def test_unknown_season_matches_no_condition(self, db_conn):
        """ESPN gives the NBA play-in no season type we map; it must not guess."""
        _pin(db_conn, start=900, season_type="postseason")
        assert _resolver(db_conn).resolve("basketball", "nba", season_type=None) is DEFAULT

    def test_conditioned_pin_outranks_unconditioned_of_same_scope(self, db_conn):
        _pin(db_conn, start=1700)
        _pin(db_conn, start=900, season_type="postseason")
        r = _resolver(db_conn)
        assert r.resolve("basketball", "nba", season_type="postseason").start == 900
        assert r.resolve("basketball", "nba", season_type="regular").start == 1700
        assert r.resolve("basketball", "nba").start == 1700

    def test_mismatch_falls_through_to_the_next_scope(self, db_conn):
        _pin(db_conn, start=900, season_type="postseason")
        _pin(db_conn, scope="sport", league_code=None, start=1800)
        r = _resolver(db_conn)
        assert r.resolve("basketball", "nba", season_type="regular").start == 1800
        assert r.resolve("basketball", "nba", season_type="postseason").start == 900

    def test_scope_still_outranks_season(self, db_conn):
        """A more specific unconditioned pin beats a conditioned broader one."""
        _pin(db_conn, start=1700)
        _pin(db_conn, scope="sport", league_code=None, start=900, season_type="postseason")
        r = _resolver(db_conn)
        assert r.resolve("basketball", "nba", season_type="postseason").start == 1700

    def test_unconditioned_pins_are_unchanged(self, db_conn):
        _pin(db_conn, start=1700)
        r = _resolver(db_conn)
        for season in (None, "regular", "postseason"):
            assert r.resolve("basketball", "nba", season_type=season).start == 1700


class TestStorage:
    def test_add_and_update_round_trip(self, db_conn):
        block = _pin(
            db_conn, start=900, season_type="Postseason", channel_group_mode="09 TEAMARR {league}"
        )
        assert block.season_type == "postseason"
        assert block.channel_group_mode == "09 TEAMARR {league}"

        kept = ne.update_numbering_exception(db_conn, block.id, start=901)
        assert (kept.season_type, kept.channel_group_mode) == ("postseason", "09 TEAMARR {league}")

        cleared = ne.update_numbering_exception(
            db_conn, block.id, season_type=None, channel_group_mode=None, channel_group_id=None
        )
        assert cleared.season_type is None
        assert not cleared.has_channel_group

    def test_invalid_season_is_rejected(self, db_conn):
        assert (
            ne.add_numbering_exception(
                db_conn, scope="league", league_code="nba", sport="basketball",
                start=900, season_type="playoffs",
            )
            is None
        )


class TestNumbering:
    def _channel(self, conn, group_id, event_id, season):
        return create_managed_channel(
            conn=conn,
            event_epg_group_id=group_id,
            event_id=event_id,
            event_provider="espn",
            tvg_id=f"tvg-{event_id}",
            channel_name=f"NBA {event_id}",
            sport="basketball",
            league="nba",
            home_team="A",
            away_team="B",
            event_date="2026-04-20T23:00:00+00:00",
            season_type=season,
        )

    def test_new_channel_numbers_from_its_season_lane(self, db_conn):
        _pin(db_conn, start=900, season_type="postseason")
        playoff = cn.get_next_channel_number(
            db_conn, "nba", sport="basketball", season_type="postseason"
        )
        regular = cn.get_next_channel_number(
            db_conn, "nba", sport="basketball", season_type="regular"
        )
        assert playoff == 900
        assert regular != 900 and not 900 <= regular <= 999

    def test_relayout_reads_the_stored_season(self, db_conn):
        """Re-layout sees only the channel row; without the stored season a
        playoff channel would drop to the default lane on the daily reset."""
        _pin(db_conn, start=900, season_type="postseason")
        group = create_group(db_conn, name="NBA", leagues=["nba"])
        playoff = self._channel(db_conn, group, "1", "postseason")
        regular = self._channel(db_conn, group, "2", "regular")
        db_conn.commit()

        cn.reassign_all_channels(db_conn)
        db_conn.commit()

        assert int(float(get_managed_channel(db_conn, playoff).channel_number)) == 900
        assert int(float(get_managed_channel(db_conn, regular).channel_number)) != 900


@pytest.fixture
def lifecycle(db_factory):
    return ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )


def _nba_event(season):
    return make_event(
        sport="basketball",
        league="nba",
        season_type=season,
        home_team=FakeTeam(name="Boston Celtics"),
        away_team=FakeTeam(id="2", name="New York Knicks"),
    )


class TestBlockChannelGroup:
    def test_block_group_applies_only_to_its_season(self, db_conn, lifecycle):
        _pin(db_conn, start=900, season_type="postseason", channel_group_mode="09 TEAMARR {league}")
        lifecycle._lane_resolver = _resolver(db_conn)
        assert lifecycle._pinned_block_group(_nba_event("postseason")) == (
            None,
            "09 TEAMARR {league}",
        )
        assert lifecycle._pinned_block_group(_nba_event("regular")) is None

    def test_block_without_a_group_defers(self, db_conn, lifecycle):
        _pin(db_conn, start=900, season_type="postseason")
        lifecycle._lane_resolver = _resolver(db_conn)
        assert lifecycle._pinned_block_group(_nba_event("postseason")) is None

    def test_static_group_id(self, db_conn, lifecycle):
        _pin(db_conn, start=900, channel_group_id=42)
        lifecycle._lane_resolver = _resolver(db_conn)
        assert lifecycle._pinned_block_group(_nba_event("regular")) == (42, "static")

    def test_no_resolver_loaded_defers(self, lifecycle):
        assert lifecycle._pinned_block_group(_nba_event("postseason")) is None

    def test_sync_uses_the_block_group_and_backfills_the_season(self, db_conn, lifecycle):
        """The sync must resolve the same group the create path did, and write
        the season onto a channel created before the column existed."""
        _pin(db_conn, start=900, season_type="postseason", channel_group_mode="09 TEAMARR {league}")
        db_conn.commit()
        lifecycle._lane_resolver = _resolver(db_conn)
        lifecycle._dynamic_resolver = MagicMock()
        lifecycle._dynamic_resolver.resolve_channel_group.return_value = 7

        with (
            patch.object(lifecycle, "_generate_channel_name", return_value="n"),
            patch.object(lifecycle, "_sync_channel_profiles"),
            patch.object(lifecycle, "_sync_channel_logo"),
            patch.object(lifecycle, "_sync_stream_profile"),
            patch("teamarr.database.channels.update_managed_channel") as update,
        ):
            lifecycle._sync_channel_settings(
                conn=db_conn,
                existing=FakeManagedChannel(),
                stream={"id": 1},
                event=_nba_event("postseason"),
                group_config={},
                template=None,
            )

        call = lifecycle._dynamic_resolver.resolve_channel_group.call_args
        assert call.kwargs["mode"] == "09 TEAMARR {league}"
        written = {}
        for c in update.call_args_list:
            written.update(c.args[2])
        assert written["season_type"] == "postseason"
