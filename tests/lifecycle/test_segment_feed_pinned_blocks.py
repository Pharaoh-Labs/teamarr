"""Segment and keyword conditions on pinned blocks (#1018).

A block may be limited to session / card-segment codes and to one kind of
channel (main, any keyword channel, driver feeds, other race feeds, one feed,
one keyword label). A row with an unsatisfied condition is not a candidate;
among candidates scope rank comes first, then a fixed key (keyword
specificity, has segments, has season), then (sort_order, id) for rows with
identical conditions. A channel's race feed comes from race_feeds by
(league, exception_keyword), not from a stored key.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.database import channel_numbers as cn
from teamarr.database import numbering_exceptions as ne
from teamarr.database.channels import create_managed_channel, get_managed_channel
from teamarr.database.groups import create_group
from teamarr.database.race_feeds import RosterEntry, upsert_roster
from teamarr.dispatcharr.types import OperationResult
from tests.fakes import FakeTeam, make_event

DEFAULT = ne.Lane(id=None, start=1600)

LECLERC = "Charles Leclerc"
LECLERC_KEY = "driver:charles-leclerc"
PIT = "Pit Lane"


@pytest.fixture(autouse=True)
def roster(db_conn):
    """Race feeds for f1: two drivers plus the variant vocabulary."""
    upsert_roster(
        db_conn,
        "f1",
        [
            RosterEntry(LECLERC, "C. Leclerc", "LEC"),
            RosterEntry("Lando Norris", "L. Norris", "NOR"),
        ],
    )


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
        assert _start(r, segment="race", exception_keyword=PIT) == 1200

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


class TestKeyword:
    def _check(self, db_conn, keyword, cases):
        _pin(db_conn, start=1300, keyword=keyword)
        r = _resolver(db_conn)
        for kwargs, expected in cases:
            assert _start(r, **kwargs) == (1300 if expected else 1600), (keyword, kwargs)

    def test_main(self, db_conn):
        self._check(
            db_conn,
            "main",
            [
                ({}, True),
                ({"exception_keyword": PIT}, False),
            ],
        )

    def test_any(self, db_conn):
        self._check(
            db_conn,
            "any",
            [
                ({}, False),
                ({"exception_keyword": PIT}, True),
                ({"exception_keyword": "Spanish"}, True),
            ],
        )

    def test_driver(self, db_conn):
        self._check(
            db_conn,
            "driver",
            [
                ({"exception_keyword": LECLERC}, True),
                ({"exception_keyword": PIT}, False),
                ({"exception_keyword": "Spanish"}, False),
                ({}, False),
            ],
        )

    def test_variant(self, db_conn):
        self._check(
            db_conn,
            "variant",
            [
                ({"exception_keyword": PIT}, True),
                ({"exception_keyword": LECLERC}, False),
                ({}, False),
            ],
        )

    def test_one_feed(self, db_conn):
        self._check(
            db_conn,
            "feed:driver:charles-leclerc",
            [
                ({"exception_keyword": LECLERC}, True),
                ({"exception_keyword": "Lando Norris"}, False),
                ({"exception_keyword": "Leclerc"}, False),  # not a race-feed label
            ],
        )

    def test_keyword_label(self, db_conn):
        self._check(
            db_conn,
            "label:Spanish",
            [
                ({"exception_keyword": "Spanish"}, True),
                ({"exception_keyword": "spanish"}, True),
                ({"exception_keyword": "French"}, False),
                ({}, False),
            ],
        )

    def test_normalization(self):
        assert ne.normalize_keyword(" MAIN ") == "main"
        assert ne.normalize_keyword("Feed:Driver:Max-Verstappen") == "feed:driver:max-verstappen"
        assert ne.normalize_keyword("LABEL:Spanish") == "label:Spanish"
        assert ne.normalize_keyword("  ") is None
        assert ne.normalize_keyword(None) is None

    @pytest.mark.parametrize(
        "bad", ["bogus", "feed:nope", "feed:driver:", "label:", "keyword:Spanish", "feed:Driver x"]
    )
    def test_invalid_keyword_is_rejected(self, db_conn, bad):
        assert (
            ne.add_numbering_exception(
                db_conn, scope="league", league_code="f1", sport="racing", start=1300, keyword=bad
            )
            is None
        )

    def test_feed_resolves_from_race_feeds_without_a_stored_key(self, db_conn):
        """A channel row carries only its keyword label; the resolver maps it."""
        _pin(db_conn, start=1300, keyword="driver")
        r = _resolver(db_conn)
        assert _start(r, exception_keyword=LECLERC) == 1300
        assert _start(r, exception_keyword=LECLERC.upper()) == 1300
        # Same label in another league is not an f1 race feed.
        assert r.resolve("racing", "indycar", exception_keyword=LECLERC) == DEFAULT

    def test_feed_condition_follows_a_refreshed_roster(self, db_conn):
        _pin(db_conn, start=1300, keyword="feed:driver:new-driver")
        assert _start(_resolver(db_conn), exception_keyword="New Driver") == 1600
        upsert_roster(db_conn, "f1", [RosterEntry("New Driver", "N. Driver", "DRI")])
        assert _start(_resolver(db_conn), exception_keyword="New Driver") == 1300


class TestPrecedence:
    """Fixed key inside a scope rank: keyword specificity, then segments, then
    season, then (sort_order, id). Condition count is not part of the key."""

    def test_segments_beat_nothing(self, db_conn):
        _pin(db_conn, start=1100)
        _pin(db_conn, start=1200, segments=["race"])
        r = _resolver(db_conn)
        assert _start(r, segment="race") == 1200
        assert _start(r, segment="fp1") == 1100

    def test_keyword_specificity_beats_segments(self, db_conn):
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, keyword="main")
        assert _start(_resolver(db_conn), segment="race") == 1300

    def test_named_feed_beats_driver_beats_any_beats_main(self, db_conn):
        _pin(db_conn, start=1100, keyword="main")
        _pin(db_conn, start=1200, keyword="any")
        _pin(db_conn, start=1300, keyword="driver")
        _pin(db_conn, start=1400, keyword=f"feed:{LECLERC_KEY}")
        r = _resolver(db_conn)
        assert _start(r, exception_keyword=LECLERC) == 1400
        assert _start(r, exception_keyword="Lando Norris") == 1300
        assert _start(r, exception_keyword="Spanish") == 1200
        assert _start(r) == 1100

    def test_named_feed_beats_named_label_in_either_insert_order(self, db_conn):
        label = {"start": 1200, "keyword": f"label:{LECLERC}"}
        feed = {"start": 1300, "keyword": f"feed:{LECLERC_KEY}"}
        _pin(db_conn, **label)
        _pin(db_conn, **feed)
        assert _start(_resolver(db_conn), exception_keyword=LECLERC) == 1300
        db_conn.execute("DELETE FROM numbering_exceptions")
        _pin(db_conn, **feed)
        _pin(db_conn, **label)
        assert _start(_resolver(db_conn), exception_keyword=LECLERC) == 1300

    def test_named_label_beats_driver_kind(self, db_conn):
        _pin(db_conn, start=1200, keyword="driver")
        _pin(db_conn, start=1300, keyword=f"label:{LECLERC}")
        assert _start(_resolver(db_conn), exception_keyword=LECLERC) == 1300

    def test_result_does_not_depend_on_row_order(self, db_conn):
        """Same blocks inserted in the opposite order resolve the same way."""
        specs = [
            {"start": 1100},
            {"start": 1200, "segments": ["race"]},
            {"start": 1300, "keyword": "main"},
            {"start": 1400, "keyword": "main", "segments": ["race"]},
            {"start": 1500, "keyword": "driver"},
        ]
        for spec in specs:
            _pin(db_conn, **spec)
        forward = _resolver(db_conn)
        db_conn.execute("DELETE FROM numbering_exceptions")
        for spec in reversed(specs):
            _pin(db_conn, **spec)
        backward = _resolver(db_conn)
        for kw in (
            {"segment": "race"},
            {"segment": "race", "exception_keyword": LECLERC},
            {"segment": "fp1"},
            {},
        ):
            assert _start(forward, **kw) == _start(backward, **kw), kw

    def test_main_with_segments_beats_main_alone(self, db_conn):
        _pin(db_conn, start=1300, keyword="main")
        _pin(db_conn, start=1400, keyword="main", segments=["race"])
        r = _resolver(db_conn)
        assert _start(r, segment="race") == 1400
        assert _start(r, segment="fp1") == 1300

    def test_segments_beat_season_at_equal_keyword(self, db_conn):
        _pin(db_conn, start=1100, season_type="postseason")
        _pin(db_conn, start=1200, segments=["race"])
        assert _start(_resolver(db_conn), season_type="postseason", segment="race") == 1200

    def test_tie_falls_to_sort_order_then_id(self, db_conn):
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, segments=["race"])
        assert _start(_resolver(db_conn), segment="race") == 1200

    def test_scope_rank_dominates(self, db_conn):
        _pin(db_conn, start=1100)
        _pin(db_conn, scope="sport", league_code=None, start=900, segments=["race"], keyword="main")
        assert _start(_resolver(db_conn), segment="race") == 1100

    def test_season_plus_segment(self, db_conn):
        _pin(db_conn, start=1100, season_type="postseason")
        _pin(db_conn, start=1200, season_type="postseason", segments=["race"])
        r = _resolver(db_conn)
        assert _start(r, season_type="postseason", segment="race") == 1200
        assert _start(r, season_type="postseason", segment="fp1") == 1100
        assert _start(r, season_type="regular", segment="race") == 1600


def _channel(conn, group, event_id, name, *, segment, kw=None, when="10:00"):
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
    )


def _number(conn, cid):
    return int(float(get_managed_channel(conn, cid).channel_number))


class TestF1Layout:
    def test_layout_through_real_rows(self, db_conn):
        _pin(
            db_conn,
            start=1200,
            segments=["race", "qualifying", "sprint_qualifying", "sprint"],
            keyword="main",
        )
        _pin(db_conn, start=1300, keyword="driver")
        _pin(db_conn, start=1400, keyword="variant")
        _pin(db_conn, start=1500)
        group = create_group(db_conn, name="F1", leagues=["f1"])
        main = {
            seg: _channel(db_conn, group, f"e-{seg}", seg, segment=seg)
            for seg in ("race", "qualifying", "sprint_qualifying", "sprint")
        }
        practice = _channel(db_conn, group, "e-fp1", "fp1", segment="fp1")
        late = _channel(
            db_conn, group, "e-d2", "d late", segment="race", kw="Lando Norris", when="14:00"
        )
        early = _channel(
            db_conn, group, "e-d1", "d early", segment="race", kw=LECLERC, when="12:00"
        )
        pit = _channel(db_conn, group, "e-pit", "pit", segment="race", kw=PIT)
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
        """A pre-upgrade row has no segment: it misses segment blocks but still
        meets ``main``, which matches a keyword-less row."""
        _pin(db_conn, start=1200, segments=["race"])
        _pin(db_conn, start=1300, keyword="main")
        _pin(db_conn, start=1500)
        group = create_group(db_conn, name="F1", leagues=["f1"])
        legacy = _channel(db_conn, group, "old", "legacy", segment=None)
        db_conn.commit()
        cn.reassign_all_channels(db_conn)
        db_conn.commit()
        assert 1300 <= _number(db_conn, legacy) <= 1399

    def test_main_and_feed_channels_of_one_event_split_lanes(self, db_conn):
        _pin(db_conn, start=1200, keyword="main")
        _pin(db_conn, start=1300, keyword="driver")
        group = create_group(db_conn, name="F1", leagues=["f1"])
        main = _channel(db_conn, group, "same", "main", segment="race")
        feed = _channel(db_conn, group, "same", "feed", segment="race", kw=LECLERC)
        db_conn.commit()
        cn.reassign_all_channels(db_conn)
        db_conn.commit()
        assert 1200 <= _number(db_conn, main) <= 1299
        assert 1300 <= _number(db_conn, feed) <= 1399

    def test_counts_use_conditions(self, db_conn):
        from teamarr.api.routes.numbering_exceptions import _with_counts

        race = _pin(db_conn, start=1200, label="F1", segments=["race"], keyword="main")
        drivers = _pin(db_conn, start=1300, label="F1", keyword="driver")
        group = create_group(db_conn, name="F1", leagues=["f1"])
        _channel(db_conn, group, "e1", "a", segment="race")
        _channel(db_conn, group, "e2", "b", segment="fp1")
        _channel(db_conn, group, "e1", "c", segment="race", kw=LECLERC)
        db_conn.commit()
        counts = {m.id: m.channel_count for m in _with_counts(db_conn, [race, drivers])}
        assert counts == {race.id: 1, drivers.id: 1}


class TestStorage:
    def test_keyword_label_with_colon_round_trips(self, db_conn):
        block = _pin(db_conn, start=1200, keyword="label:Live: English")
        assert block.keyword == "label:Live: English"
        assert _start(_resolver(db_conn), exception_keyword="live: english") == 1200

    def test_channel_row_keeps_segment_and_keyword(self, db_conn):
        group = create_group(db_conn, name="F1", leagues=["f1"])
        cid = _channel(db_conn, group, "e1", "n", segment="race", kw=LECLERC)
        ch = get_managed_channel(db_conn, cid)
        assert (ch.segment, ch.exception_keyword) == ("race", LECLERC)
        assert not hasattr(ch, "feed_key")

    def test_managed_channels_has_no_feed_key_column(self, db_conn):
        cols = {r["name"] for r in db_conn.execute("PRAGMA table_info(managed_channels)")}
        assert "segment" in cols
        assert "feed_key" not in cols

    def test_next_number_reads_new_inputs(self, db_conn):
        _pin(db_conn, start=1300, keyword="driver")
        assert (
            cn.get_next_channel_number(db_conn, "f1", sport="racing", exception_keyword=LECLERC)
            == 1300
        )
        assert cn.get_next_channel_number(db_conn, "f1", sport="racing") != 1300

    def test_block_round_trip_and_clear(self, db_conn):
        block = _pin(db_conn, start=1200, segments=["Race"], keyword="Driver")
        assert (block.segments, block.keyword) == (["race"], "driver")
        kept = ne.update_numbering_exception(db_conn, block.id, start=1201)
        assert (kept.segments, kept.keyword) == (["race"], "driver")
        cleared = ne.update_numbering_exception(db_conn, block.id, segments=None, keyword=None)
        assert (cleared.segments, cleared.keyword) == (None, None)

    def test_invalid_update_returns_none(self, db_conn):
        block = _pin(db_conn, start=1200)
        assert ne.update_numbering_exception(db_conn, block.id, keyword="bogus") is None


class TestSegmentCodes:
    def test_known_codes_cover_racing_and_mma(self):
        codes = ne.known_segment_codes()
        assert "race" in codes["racing"] and "sprint_qualifying" in codes["racing"]
        assert codes["mma"] == ("early_prelims", "prelims", "main_card")

    @pytest.mark.parametrize("seg", ["qualy", "practice", "bad code!"])
    def test_unknown_segment_is_rejected(self, db_conn, seg):
        assert (
            ne.add_numbering_exception(
                db_conn,
                scope="league",
                league_code="f1",
                sport="racing",
                start=1300,
                segments=[seg],
            )
            is None
        )

    def test_known_codes_accepted_per_sport(self, db_conn):
        assert _pin(db_conn, start=1300, segments=["qualifying", "race"]).segments == [
            "qualifying",
            "race",
        ]
        mma = _pin(
            db_conn,
            scope="sport",
            league_code=None,
            sport="mma",
            start=1400,
            segments=["main_card"],
        )
        assert mma.segments == ["main_card"]

    def test_other_sports_codes_are_rejected(self, db_conn):
        # main_card is an MMA code, race is a racing code.
        assert (
            ne.add_numbering_exception(
                db_conn,
                scope="league",
                league_code="f1",
                sport="racing",
                start=1300,
                segments=["main_card"],
            )
            is None
        )
        assert (
            ne.add_numbering_exception(
                db_conn, scope="sport", sport="mma", start=1300, segments=["race"]
            )
            is None
        )

    def test_league_sport_is_resolved_before_checking_codes(self, db_conn):
        """No sport passed: a league block takes it from the leagues table."""
        db_conn.execute(
            "INSERT OR REPLACE INTO leagues "
            "(league_code, provider, provider_league_id, display_name, sport) "
            "VALUES ('ufc', 'espn', 'ufc', 'UFC', 'mma')"
        )
        assert (
            ne.add_numbering_exception(
                db_conn, scope="league", league_code="ufc", start=1300, segments=["race"]
            )
            is None
        )
        ok = ne.add_numbering_exception(
            db_conn, scope="league", league_code="ufc", start=1300, segments=["main_card"]
        )
        assert ok is not None and ok.sport == "mma"

    def test_non_segment_sport_rejects_segments(self, db_conn):
        assert (
            ne.add_numbering_exception(
                db_conn, scope="sport", sport="football", start=1300, segments=["race"]
            )
            is None
        )

    def test_update_checks_codes_against_the_blocks_sport(self, db_conn):
        block = _pin(db_conn, start=1300)
        assert ne.update_numbering_exception(db_conn, block.id, segments=["main_card"]) is None
        assert ne.update_numbering_exception(db_conn, block.id, segments=["race"]) is not None


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


class TestChannelGroup:
    def test_group_resolves_per_channel(self, db_conn, lifecycle):
        _pin(db_conn, start=1300, keyword="driver", channel_group_mode="Drivers")
        _pin(db_conn, start=1200, keyword="main", channel_group_mode="Main")
        lifecycle._lane_resolver = _resolver(db_conn)
        ev = _f1_event()
        assert lifecycle._pinned_block_group(ev, "race") == (None, "Main")
        assert lifecycle._pinned_block_group(ev, "race", LECLERC) == (None, "Drivers")
        assert lifecycle._pinned_block_group(ev, "race", PIT) is None


class TestCreationPath:
    """_create_channel stores the segment and the keyword label, nothing else."""

    def _create(self, db_conn, lifecycle, stream_name, segment, label):
        group = create_group(db_conn, name="F1", leagues=["f1"])
        db_conn.commit()
        lifecycle._channel_manager.create_channel.return_value = OperationResult(
            success=True, channel={"id": 100 + len(stream_name), "uuid": f"u-{stream_name}"}
        )
        with (
            patch.object(lifecycle, "_generate_channel_name", return_value=stream_name),
            patch.object(lifecycle, "_get_next_channel_number", return_value="1200"),
            patch.object(lifecycle, "_resolve_logo_url", return_value=None),
            patch.object(lifecycle._timing_manager, "calculate_delete_time", return_value=None),
        ):
            result = lifecycle._create_channel(
                conn=db_conn,
                event=_f1_event(),
                stream={"id": len(stream_name), "name": stream_name},
                group_config={"id": group},
                template=None,
                matched_keyword=label,
                channel_group_id=None,
                channel_profile_ids=[],
                segment=segment,
            )
        assert result.success
        return db_conn.execute(
            "SELECT segment, exception_keyword FROM managed_channels"
            " WHERE dispatcharr_channel_id = ?",
            (100 + len(stream_name),),
        ).fetchone()

    def test_driver_channel_stores_segment_and_keyword(self, db_conn, lifecycle):
        row = self._create(db_conn, lifecycle, "F1 Onboard Charles Leclerc", "race", LECLERC)
        assert (row["segment"], row["exception_keyword"]) == ("race", LECLERC)

    def test_main_channel_has_no_keyword(self, db_conn, lifecycle):
        row = self._create(db_conn, lifecycle, "F1 Race Live", "race", None)
        assert (row["segment"], row["exception_keyword"]) == ("race", None)


class TestApi:
    @contextmanager
    def _db(self, conn):
        yield conn

    def test_round_trip_and_clear(self, db_conn):
        from teamarr.api.routes import numbering_exceptions as api

        with patch.object(api, "get_db", lambda: self._db(db_conn)):
            made = api.create_numbering_exception(
                api.NumberingExceptionCreate(
                    scope="league",
                    league_code="f1",
                    sport="racing",
                    start=1200,
                    segments=["race", "sprint"],
                    keyword="driver",
                )
            )
            assert (made.segments, made.keyword) == (["race", "sprint"], "driver")

            same = api.update(made.id, api.NumberingExceptionUpdate(start=1201))
            assert (same.segments, same.keyword) == (["race", "sprint"], "driver")

            cleared = api.update(
                made.id,
                api.NumberingExceptionUpdate(
                    segments=None, set_segments=True, keyword=None, set_keyword=True
                ),
            )
            assert (cleared.segments, cleared.keyword) == (None, None)

    def test_invalid_segment_create_is_400_and_update_is_422(self, db_conn):
        from fastapi import HTTPException

        from teamarr.api.routes import numbering_exceptions as api

        with patch.object(api, "get_db", lambda: self._db(db_conn)):
            with pytest.raises(HTTPException) as err:
                api.create_numbering_exception(
                    api.NumberingExceptionCreate(
                        scope="league",
                        league_code="f1",
                        sport="racing",
                        start=1200,
                        segments=["qualy"],
                    )
                )
            assert err.value.status_code == 400
            block = _pin(db_conn, start=1300)
            with pytest.raises(HTTPException) as err:
                api.update(
                    block.id,
                    api.NumberingExceptionUpdate(segments=["qualy"], set_segments=True),
                )
            assert err.value.status_code == 422

    def test_update_missing_block_is_404(self, db_conn):
        from fastapi import HTTPException

        from teamarr.api.routes import numbering_exceptions as api

        with patch.object(api, "get_db", lambda: self._db(db_conn)):
            with pytest.raises(HTTPException) as err:
                api.update(99999, api.NumberingExceptionUpdate(start=1201))
            assert err.value.status_code == 404

    def test_segment_codes_endpoint(self):
        from teamarr.api.routes import numbering_exceptions as api

        codes = api.segment_codes()
        assert "race" in codes["racing"]
        assert "main_card" in codes["mma"]

    def test_member_label_names_conditions(self, db_conn):
        from teamarr.api.routes.numbering_exceptions import _member_label

        block = _pin(db_conn, start=1200, label="F1", segments=["race"], keyword="driver")
        label = _member_label(db_conn, block)
        assert "race" in label and "driver" in label
