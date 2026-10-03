"""What happens to streams with no home/away label when a game has feeds (#828).

With feed separation on, a game whose provider labels some streams and leaves
others bare became three channels: home feed, away feed, and a third holding
everything unlabelled. The ``unlabeled_streams`` setting chooses between that
('separate', the default) and skipping the unlabelled streams for such a game
('ignore'). Nothing is ever assigned to a side.
"""

from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.database.settings import get_feed_separation_settings, update_feed_separation_settings
from tests.fakes import FakeChannel, FakeGroup, FakeTeam, make_event

HOME = FakeTeam(id="10", name="New York Yankees")
AWAY = FakeTeam(id="6", name="Detroit Tigers")


def _game(event_id="401", sport="baseball", league="mlb"):
    return make_event(id=event_id, sport=sport, league=league, home_team=HOME, away_team=AWAY)


def _entry(stream_id, event, feed_team=None, segment=None):
    entry = {"stream": {"id": stream_id, "name": f"s{stream_id}"}, "event": event,
             "feed_team": feed_team}
    if segment:
        entry["segment"] = segment
    return entry


def _drop(entries, existing_feed_events=(), sports=None, disabled_leagues=None):
    with patch(
        "teamarr.database.channels.crud.get_feed_separated_event_ids",
        return_value=set(existing_feed_events),
    ):
        return StreamMatching()._drop_unlabelled_feed_streams(
            entries, MagicMock(), sports, disabled_leagues
        )


def _ids(entries):
    return [e["stream"]["id"] for e in entries]


class TestIgnorePolicy:
    def test_unlabelled_stream_is_dropped_when_the_game_has_a_feed(self):
        game = _game()
        kept, dropped, _ = _drop(
            [_entry(1, game, HOME), _entry(2, game, AWAY), _entry(3, game)]
        )
        assert _ids(kept) == [1, 2]
        assert _ids(dropped) == [3]

    def test_game_with_no_feed_keeps_every_stream(self):
        """The rule that makes this safe: no labelled feed, nothing dropped."""
        game = _game()
        kept, dropped, _ = _drop([_entry(1, game), _entry(2, game)])
        assert _ids(kept) == [1, 2] and dropped == []

    def test_only_the_game_with_feeds_is_affected(self):
        split, plain = _game("401"), _game("402")
        kept, dropped, _ = _drop(
            [_entry(1, split, HOME), _entry(2, split), _entry(3, plain)]
        )
        assert _ids(kept) == [1, 3]
        assert _ids(dropped) == [2]

    def test_a_feed_channel_from_another_source_counts(self):
        """Feeds and bare streams often come from different sources: the feed
        is then an existing channel, not a stream in this batch."""
        game = _game()
        kept, dropped, _ = _drop([_entry(3, game)], existing_feed_events={"401"})
        assert kept == [] and _ids(dropped) == [3]

    def test_segments_are_separate_games(self):
        card = _game("600053", sport="mma", league="ufc")
        kept, dropped, _ = _drop(
            [
                _entry(1, card, HOME, segment="main_card"),
                _entry(2, card, segment="main_card"),
                _entry(3, card, segment="prelims"),
            ]
        )
        assert _ids(kept) == [1, 3]
        assert _ids(dropped) == [2]

    def test_sport_outside_the_separated_list_is_untouched(self):
        game = _game(sport="hockey", league="nhl")
        kept, dropped, _ = _drop(
            [_entry(3, game)], existing_feed_events={"401"}, sports=["baseball"]
        )
        assert _ids(kept) == [3] and dropped == []

    def test_league_with_separation_switched_off_is_untouched(self):
        game = _game()
        kept, dropped, _ = _drop(
            [_entry(3, game)], existing_feed_events={"401"}, disabled_leagues={"mlb"}
        )
        assert _ids(kept) == [3] and dropped == []


class TestThirdChannelCleanup:
    @staticmethod
    def _cleanup(channels, event_ids):
        processor = StreamMatching()
        lifecycle = MagicMock()
        lifecycle.delete_managed_channel.return_value = True
        processor._get_lifecycle_service = lambda: lifecycle
        with patch(
            "teamarr.database.channels.get_managed_channels_for_group", return_value=channels
        ):
            deleted = processor._cleanup_unlabelled_feed_channels(
                FakeGroup(), MagicMock(), event_ids
            )
        return deleted, [c.args[1] for c in lifecycle.delete_managed_channel.call_args_list]

    def test_removes_the_unlabelled_channel_and_keeps_the_feeds(self):
        channels = [
            FakeChannel(id=1, event_id="401", feed_team_id=None),
            FakeChannel(id=2, event_id="401", feed_team_id="10"),
            FakeChannel(id=3, event_id="401", feed_team_id="6"),
        ]
        assert self._cleanup(channels, {"401"}) == (1, [1])

    def test_other_games_are_left_alone(self):
        channels = [FakeChannel(id=1, event_id="402", feed_team_id=None)]
        assert self._cleanup(channels, {"401"}) == (0, [])

    def test_nothing_dropped_means_nothing_looked_up(self):
        with patch("teamarr.database.channels.get_managed_channels_for_group") as lookup:
            assert StreamMatching()._cleanup_unlabelled_feed_channels(
                FakeGroup(), MagicMock(), set()
            ) == 0
        lookup.assert_not_called()


class TestSetting:
    def test_default_keeps_the_third_channel(self, db_conn):
        assert get_feed_separation_settings(db_conn).unlabeled_streams == "separate"

    def test_round_trip(self, db_conn):
        assert update_feed_separation_settings(db_conn, unlabeled_streams="ignore")
        assert get_feed_separation_settings(db_conn).unlabeled_streams == "ignore"

    @pytest.mark.parametrize("value", ["home", "away", "merge", ""])
    def test_no_option_assigns_a_side(self, db_conn, value):
        """Only 'separate' and 'ignore' exist: an unknown side is never guessed."""
        assert update_feed_separation_settings(db_conn, unlabeled_streams=value) is False
        assert get_feed_separation_settings(db_conn).unlabeled_streams == "separate"


def test_feed_event_ids_come_from_live_feed_channels_only(db_conn):
    from teamarr.database.channels import create_managed_channel, mark_channel_deleted
    from teamarr.database.channels.crud import get_feed_separated_event_ids
    from teamarr.database.groups import create_group

    group = create_group(db_conn, name="G", leagues=["mlb"])

    def channel(event_id, feed):
        return create_managed_channel(
            conn=db_conn, event_epg_group_id=group, event_id=event_id, event_provider="espn",
            tvg_id=f"tvg-{event_id}-{feed}", channel_name=f"c-{event_id}-{feed}",
            feed_team_id=feed,
        )

    channel("401", "10")
    channel("402", None)
    gone = channel("403", "6")
    mark_channel_deleted(db_conn, gone, "test")

    assert get_feed_separated_event_ids(db_conn) == {"401"}


def test_dropped_streams_are_marked_in_run_history(db_conn):
    from teamarr.database.groups import create_group
    from teamarr.database.stats import create_run, mark_matched_streams_excluded

    group = create_group(db_conn, name="G", leagues=["mlb"])
    run = create_run(db_conn, "full_epg").id
    db_conn.executemany(
        "INSERT INTO epg_matched_streams (run_id, group_id, group_name, stream_id, "
        "stream_name, event_id, event_name) VALUES (?, ?, 'G', ?, ?, '401', 'DET at NYY')",
        [(run, group, 3, "s3"), (run, group, 1, "s1")],
    )

    assert mark_matched_streams_excluded(db_conn, run, group, [(3, "401")], "unlabeled_feed") == 1

    rows = {
        r["stream_id"]: (r["excluded"], r["exclusion_reason"])
        for r in db_conn.execute(
            "SELECT stream_id, excluded, exclusion_reason FROM epg_matched_streams"
        )
    }
    assert rows[3] == (1, "unlabeled_feed")
    assert rows[1][0] in (0, None)
