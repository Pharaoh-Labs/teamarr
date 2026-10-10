"""Segment and feed conditions on pinned blocks (#1018).

A block may be limited to session / card-segment codes and to one kind of
channel (main, any keyword channel, driver feeds, other race feeds, one feed,
one keyword label). A row with an unsatisfied condition is not a candidate;
among candidates scope rank comes first, then the most satisfied conditions,
then (sort_order, id).
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.database import channel_numbers as cn
from teamarr.database import numbering_exceptions as ne
from teamarr.database.channels import create_managed_channel, get_managed_channel
from teamarr.database.exception_keywords import ExceptionKeyword
from teamarr.database.groups import create_group
from teamarr.database.race_feeds import (
    RosterEntry,
    list_race_feeds,
    update_race_feed,
    upsert_roster,
)
from teamarr.dispatcharr.types import OperationResult
from tests.fakes import FakeTeam, make_event

DEFAULT = ne.Lane(id=None, start=1600)


def _pin(conn, **kw):
    kw.setdefault("scope", "league")
    kw.setdefault("league_code", "f1")
    kw.setdefault("sport", "racing")
    block = ne.add_numbering_exception(conn, **kw)
    assert block is not None
    return block


def _resolver(conn):
    return ne.LaneResolver.load(conn, DEFAULT)


def _start(r, **kw):
    return r.resolve("racing", "f1", **kw).start


class TestUnconditionedUnchanged:
    def test_new_inputs_do_not_affect_plain_rows(self, db_conn):
        _pin(db_conn, start=1200)
        r = _resolver(db_conn)
        assert _start(r) == 1200
        assert _start(r, segment="race", exception_keyword="Pit Lane", feed_key="variant:x") == 1200

    def test_season_only_tie_break_is_as_before(self, db_conn):
        _pin(db_conn, start=1100)
        _pin(db_conn, start=900, season_type="postseason")
        r = _resolver(db_conn)
        assert _start(r, season_type="postseason") == 900
        assert _start(r, season_type="regular") == 1100


class TestSegments:
    def test_match_and_miss(self, db_conn):
        _pin(db_conn, start=1200, segments=["race", "qualifying"])
        r = _resolver(db_conn)
        assert _start(r, segment="race") == 1200
        assert _start(r, segment="Qualifying") == 1200
        assert _start(r, segment="practice") == 1600

    def test_channel_without_segment_matches_no_condition(self, db_conn):
        _pin(db_conn, start=1200, segments=["race"])
        assert _start(_resolver(db_conn), segment=None) == 1600

    def test_segments_are_normalized(self, db_conn):
        block = _pin(db_conn, start=1200, segments=" Race, qualifying ,race,,")
        assert block.segments == ["race", "qualifying"]
        assert ne.normalize_segments("") is None
        assert ne.normalize_segments([" ", ""]) is None
        assert ne.normalize_segments(None) is None


class TestFeeds:
    def _check(self, db_conn, feed, cases):
        _pin(db_conn, start=1300, feed=feed)
        r = _resolver(db_conn)
        for kwargs, expected in cases:
            assert _start(r, **kwargs) == (1300 if expected else 1600), (feed, kwargs)

    def test_main(self, db_conn):
        self._check(
            db_conn,
            "main",
            [
                ({}, True),
                ({"exception_keyword": "Pit Lane", "feed_key": "variant:pit-lane"}, False),
            ],
        )

    def test_any(self, db_conn):
        self._check(
            db_conn,
            "any",
            [({}, False), ({"exception_keyword": "Pit Lane", "feed_key": "variant:pit-lane"}, True),
             ({"exception_keyword": "Spanish"}, True)],
        )

    def test_driver(self, db_conn):
        self._check(
            db_conn,
            "driver",
            [
                ({"exception_keyword": "Leclerc", "feed_key": "driver:charles-leclerc"}, True),
                ({"exception_keyword": "Pit Lane", "feed_key": "variant:pit-lane"}, False),
                ({"exception_keyword": "Spanish"}, False),
                ({}, False),
            ],
        )

    def test_variant(self, db_conn):
        self._check(
            db_conn,
            "variant",
            [
                ({"exception_keyword": "Pit Lane", "feed_key": "variant:pit-lane"}, True),
                ({"exception_keyword": "Leclerc", "feed_key": "driver:charles-leclerc"}, False),
                ({}, False),
            ],
        )

    def test_one_feed(self, db_conn):
        self._check(
            db_conn,
            "feed:driver:charles-leclerc",
            [
                ({"exception_keyword": "Leclerc", "feed_key": "driver:charles-leclerc"}, True),
                ({"exception_keyword": "Norris", "feed_key": "driver:lando-norris"}, False),
                ({"exception_keyword": "Leclerc"}, False),
            ],
        )

    def test_keyword_label(self, db_conn):
        self._check(
            db_conn,
            "keyword:Spanish",
            [
                ({"exception_keyword": "Spanish"}, True),
                ({"exception_keyword": "spanish"}, True),
                ({"exception_keyword": "French"}, False),
                ({}, False),
            ],
        )

    def test_normalization(self):
        assert ne.normalize_feed(" MAIN ") == "main"
        assert ne.normalize_feed("Feed:Driver:Max-Verstappen") == "feed:driver:max-verstappen"
        assert ne.normalize_feed("KEYWORD:Spanish") == "keyword:Spanish"
        assert ne.normalize_feed("  ") is None
        assert ne.normalize_feed(None) is None

    @pytest.mark.parametrize(
        "bad", ["bogus", "feed:nope", "feed:driver:", "keyword:", "feed:Driver x"]
    )
    def test_invalid_feed_is_rejected(self, db_conn, bad):
        assert (
            ne.add_numbering_exception(
                db_conn, scope="league", league_code="f1", sport="racing", start=1300, feed=bad
            )
            is None
        )


class TestPrecedence:
    def test_two_conditions_beat_one_beat_none(self, db_conn):
        _pin(db_conn, start=1100)
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, segments=["race"], feed="main")
        r = _resolver(db_conn)
        assert _start(r, segment="race") == 1300
        assert _start(r, segment="race", exception_keyword="Pit Lane") == 1200
        assert _start(r, segment="practice") == 1100

    def test_tie_falls_to_sort_order_then_id(self, db_conn):
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, feed="main")
        assert _start(_resolver(db_conn), segment="race") == 1200

    def test_scope_rank_dominates(self, db_conn):
        _pin(db_conn, start=1100)
        _pin(db_conn, scope="sport", league_code=None, start=900, segments=["race"], feed="main")
        assert _start(_resolver(db_conn), segment="race") == 1100

    def test_season_plus_segment(self, db_conn):
        _pin(db_conn, start=1100, season_type="postseason")
        _pin(db_conn, start=1200, season_type="postseason", segments=["race"])
        r = _resolver(db_conn)
        assert _start(r, season_type="postseason", segment="race") == 1200
        assert _start(r, season_type="postseason", segment="practice") == 1100
        assert _start(r, season_type="regular", segment="race") == 1600


def _channel(conn, group, event_id, name, *, segment, kw=None, feed_key=None, when="10:00"):
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=group,
        event_id=event_id,
        event_provider="espn",
        tvg_id=f"tvg-{event_id}-{kw}",
        channel_name=name,
        sport="racing",
        league="f1",
        home_team="A",
        away_team="B",
        event_date=f"2026-10-04T{when}:00+00:00",
        exception_keyword=kw,
        segment=segment,
        feed_key=feed_key,
    )


def _number(conn, cid):
    return int(float(get_managed_channel(conn, cid).channel_number))


class TestF1Layout:
    def test_layout_through_real_rows(self, db_conn):
        _pin(db_conn, start=1200, segments=["race", "qualifying", "sprint_qualifying", "sprint"],
             feed="main")
        _pin(db_conn, start=1300, feed="driver")
        _pin(db_conn, start=1400, feed="variant")
        _pin(db_conn, start=1500)
        group = create_group(db_conn, name="F1", leagues=["f1"])
        main = {
            seg: _channel(db_conn, group, f"e-{seg}", seg, segment=seg)
            for seg in ("race", "qualifying", "sprint_qualifying", "sprint")
        }
        practice = _channel(db_conn, group, "e-fp1", "fp1", segment="fp1")
        late = _channel(db_conn, group, "e-d2", "d late", segment="race", kw="Norris",
                        feed_key="driver:lando-norris", when="14:00")
        early = _channel(db_conn, group, "e-d1", "d early", segment="race", kw="Leclerc",
                         feed_key="driver:charles-leclerc", when="12:00")
        pit = _channel(db_conn, group, "e-pit", "pit", segment="race", kw="Pit Lane",
                       feed_key="variant:pit-lane")
        db_conn.commit()

        cn.reassign_all_channels(db_conn)
        db_conn.commit()

        for cid in main.values():
            assert 1200 <= _number(db_conn, cid) <= 1299
        for cid in (early, late):
            assert 1300 <= _number(db_conn, cid) <= 1399
        assert _number(db_conn, early) < _number(db_conn, late)
        assert 1400 <= _number(db_conn, pit) <= 1499
        assert 1500 <= _number(db_conn, practice) <= 1599

    def test_null_rows_match_no_segment_or_race_feed_condition(self, db_conn):
        """A pre-upgrade row has no segment and no feed key: it misses segments,
        driver, variant and single-feed blocks but still meets ``main``."""
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, feed="main")
        _pin(db_conn, start=1500)
        group = create_group(db_conn, name="F1", leagues=["f1"])
        legacy = _channel(db_conn, group, "old", "legacy", segment=None)
        db_conn.commit()
        cn.reassign_all_channels(db_conn)
        db_conn.commit()
        # feed=main matches a keyword-less row, so it is the only conditioned hit.
        assert 1300 <= _number(db_conn, legacy) <= 1399

    def test_main_and_feed_channels_of_one_event_split_lanes(self, db_conn):
        _pin(db_conn, start=1200, feed="main")
        _pin(db_conn, start=1300, feed="driver")
        group = create_group(db_conn, name="F1", leagues=["f1"])
        main = _channel(db_conn, group, "same", "main", segment="race")
        feed = _channel(db_conn, group, "same", "feed", segment="race", kw="Leclerc",
                        feed_key="driver:charles-leclerc")
        db_conn.commit()
        cn.reassign_all_channels(db_conn)
        db_conn.commit()
        assert 1200 <= _number(db_conn, main) <= 1299
        assert 1300 <= _number(db_conn, feed) <= 1399

    def test_counts_use_conditions(self, db_conn):
        from teamarr.api.routes.numbering_exceptions import _with_counts

        race = _pin(db_conn, start=1200, label="F1", segments=["race"], feed="main")
        drivers = _pin(db_conn, start=1300, label="F1", feed="driver")
        group = create_group(db_conn, name="F1", leagues=["f1"])
        _channel(db_conn, group, "e1", "a", segment="race")
        _channel(db_conn, group, "e2", "b", segment="fp1")
        _channel(db_conn, group, "e1", "c", segment="race", kw="Leclerc",
                 feed_key="driver:charles-leclerc")
        db_conn.commit()
        counts = {m.id: m.channel_count for m in _with_counts(db_conn, [race, drivers])}
        assert counts == {race.id: 1, drivers.id: 1}


class TestStorage:
    def test_keyword_label_with_colon_round_trips(self, db_conn):
        block = _pin(db_conn, start=1200, feed="keyword:Live: English")
        assert block.feed == "keyword:Live: English"
        assert _start(
            _resolver(db_conn), exception_keyword="live: english"
        ) == 1200

    def test_channel_row_keeps_segment_and_feed_key(self, db_conn):
        group = create_group(db_conn, name="F1", leagues=["f1"])
        cid = _channel(db_conn, group, "e1", "n", segment="race", kw="Leclerc",
                       feed_key="driver:charles-leclerc")
        ch = get_managed_channel(db_conn, cid)
        assert (ch.segment, ch.feed_key) == ("race", "driver:charles-leclerc")

    def test_next_number_reads_new_inputs(self, db_conn):
        _pin(db_conn, start=1300, feed="driver")
        assert (
            cn.get_next_channel_number(
                db_conn, "f1", sport="racing", exception_keyword="Leclerc",
                feed_key="driver:charles-leclerc",
            )
            == 1300
        )
        assert cn.get_next_channel_number(db_conn, "f1", sport="racing") != 1300

    def test_block_round_trip_and_clear(self, db_conn):
        block = _pin(db_conn, start=1200, segments=["Race"], feed="Driver")
        assert (block.segments, block.feed) == (["race"], "driver")
        kept = ne.update_numbering_exception(db_conn, block.id, start=1201)
        assert (kept.segments, kept.feed) == (["race"], "driver")
        cleared = ne.update_numbering_exception(db_conn, block.id, segments=None, feed=None)
        assert (cleared.segments, cleared.feed) == (None, None)

    def test_invalid_update_returns_none(self, db_conn):
        block = _pin(db_conn, start=1200)
        assert ne.update_numbering_exception(db_conn, block.id, feed="bogus") is None


@pytest.fixture
def lifecycle(db_factory):
    return ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )


def _f1_event():
    return make_event(
        sport="racing",
        league="f1",
        home_team=FakeTeam(name="Home"),
        away_team=FakeTeam(id="2", name="Away"),
    )


class TestChannelGroupAndFeedKey:
    def test_group_resolves_per_channel(self, db_conn, lifecycle):
        _pin(db_conn, start=1300, feed="driver", channel_group_mode="Drivers")
        _pin(db_conn, start=1200, feed="main", channel_group_mode="Main")
        lifecycle._lane_resolver = _resolver(db_conn)
        ev = _f1_event()
        assert lifecycle._pinned_block_group(ev, "race") == (None, "Main")
        assert lifecycle._pinned_block_group(
            ev, "race", "Leclerc", "driver:charles-leclerc"
        ) == (None, "Drivers")
        assert lifecycle._pinned_block_group(ev, "race", "Pit Lane", "variant:pit-lane") is None

    def test_feed_key_for_maps_label_to_race_feed(self, lifecycle):
        kws = [
            ExceptionKeyword(id=1, label="Leclerc", match_terms="Leclerc", behavior="separate",
                             feed_key="driver:charles-leclerc"),
            ExceptionKeyword(id=2, label="Spanish", match_terms="Spanish", behavior="separate"),
        ]
        lifecycle.__dict__["_league_keywords"] = {"f1": kws}
        ev = _f1_event()
        assert lifecycle._feed_key_for(ev, "Leclerc") == "driver:charles-leclerc"
        assert lifecycle._feed_key_for(ev, "Spanish") is None
        assert lifecycle._feed_key_for(ev, None) is None


class TestCreationPath:
    """Real keyword match -> feed key -> _create_channel -> stored row."""

    def _create(self, db_conn, lifecycle, stream_name, segment, behavior="consolidate"):
        upsert_roster(db_conn, "f1", [RosterEntry("Charles Leclerc", "C. Leclerc", "LEC")])
        for feed in list_race_feeds(db_conn, "f1"):
            update_race_feed(db_conn, feed.id, behavior=behavior)
        group = create_group(db_conn, name="F1", leagues=["f1"])
        db_conn.commit()
        lifecycle._channel_manager.create_channel.return_value = OperationResult(
            success=True, channel={"id": 100 + len(stream_name), "uuid": f"u-{stream_name}"}
        )
        event = _f1_event()
        kw = lifecycle._match_exception_keyword(stream_name, db_conn, event)
        label = kw.label if kw else None
        feed_key = lifecycle._feed_key_for(event, label, kw)
        with (
            patch.object(lifecycle, "_generate_channel_name", return_value=stream_name),
            patch.object(lifecycle, "_get_next_channel_number", return_value="1200"),
            patch.object(lifecycle, "_resolve_logo_url", return_value=None),
            patch.object(lifecycle._timing_manager, "calculate_delete_time", return_value=None),
        ):
            result = lifecycle._create_channel(
                conn=db_conn,
                event=event,
                stream={"id": len(stream_name), "name": stream_name},
                group_config={"id": group},
                template=None,
                matched_keyword=label,
                channel_group_id=None,
                channel_profile_ids=[],
                feed_key=feed_key,
                segment=segment,
            )
        assert result.success
        row = db_conn.execute(
            "SELECT segment, feed_key, exception_keyword FROM managed_channels"
            " WHERE dispatcharr_channel_id = ?",
            (100 + len(stream_name),),
        ).fetchone()
        return row

    def test_consolidate_driver_feed_stores_key_and_keyword(self, db_conn, lifecycle):
        row = self._create(db_conn, lifecycle, "F1 Onboard Charles Leclerc", "RACE")
        assert (row["segment"], row["feed_key"], row["exception_keyword"]) == (
            "race", "driver:charles-leclerc", "Charles Leclerc",
        )

    def test_separate_driver_feed_stores_key(self, db_conn, lifecycle):
        row = self._create(
            db_conn, lifecycle, "F1 Onboard Charles Leclerc", "qualifying", "separate"
        )
        assert row["feed_key"] == "driver:charles-leclerc"

    def test_main_channel_has_no_feed_key(self, db_conn, lifecycle):
        row = self._create(db_conn, lifecycle, "F1 Race Live", "race")
        assert (row["segment"], row["feed_key"], row["exception_keyword"]) == ("race", None, None)

    def test_matched_object_beats_label_lookup(self, lifecycle):
        """A global keyword sharing a feed's label must not inherit the feed key."""
        feed = ExceptionKeyword(id=1, label="Pit Lane", match_terms="Pit Lane",
                                behavior="separate", feed_key="variant:pit-lane")
        glob = ExceptionKeyword(id=2, label="Pit Lane", match_terms="PL", behavior="separate")
        lifecycle.__dict__["_league_keywords"] = {"f1": [feed, glob]}
        ev = _f1_event()
        assert lifecycle._feed_key_for(ev, "Pit Lane", glob) is None
        assert lifecycle._feed_key_for(ev, "Pit Lane", feed) == "variant:pit-lane"
        assert lifecycle._feed_key_for(ev, "Pit Lane") == "variant:pit-lane"


class TestApi:
    @contextmanager
    def _db(self, conn):
        yield conn

    def test_round_trip_and_clear(self, db_conn):
        from teamarr.api.routes import numbering_exceptions as api

        with patch.object(api, "get_db", lambda: self._db(db_conn)):
            made = api.create_numbering_exception(
                api.NumberingExceptionCreate(
                    scope="league", league_code="f1", sport="racing", start=1200,
                    segments=["race", "sprint"], feed="driver",
                )
            )
            assert (made.segments, made.feed) == (["race", "sprint"], "driver")

            same = api.update(made.id, api.NumberingExceptionUpdate(start=1201))
            assert (same.segments, same.feed) == (["race", "sprint"], "driver")

            cleared = api.update(
                made.id,
                api.NumberingExceptionUpdate(
                    segments=None, set_segments=True, feed=None, set_feed=True
                ),
            )
            assert (cleared.segments, cleared.feed) == (None, None)

    def test_invalid_segment_is_rejected(self, db_conn):
        from fastapi import HTTPException

        from teamarr.api.routes import numbering_exceptions as api

        with patch.object(api, "get_db", lambda: self._db(db_conn)):
            with pytest.raises(HTTPException) as err:
                api.create_numbering_exception(
                    api.NumberingExceptionCreate(
                        scope="league", league_code="f1", sport="racing", start=1200,
                        segments=["bad code!"],
                    )
                )
            assert err.value.status_code == 400
            block = _pin(db_conn, start=1300)
            with pytest.raises(HTTPException) as err:
                api.update(
                    block.id,
                    api.NumberingExceptionUpdate(segments=["bad code!"], set_segments=True),
                )
            assert err.value.status_code == 404

    def test_member_label_names_conditions(self, db_conn):
        from teamarr.api.routes.numbering_exceptions import _member_label

        block = _pin(db_conn, start=1200, label="F1", segments=["race"], feed="driver")
        label = _member_label(db_conn, block)
        assert "race" in label and "driver" in label
