"""Source discovery: scan M3U groups that are not sources (#997)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.consumers.matching import StreamCategory
from teamarr.consumers.source_lifecycle.discovery import (
    EVIDENCE_WINDOW_DAYS,
    TIER_GAMES,
    TIER_NAME_ONLY,
    TIER_TEAMS,
    SourceDiscovery,
    accept_candidate,
    fold_same_content,
    is_replay_group,
    league_name_surfaces,
    leagues_named_by,
    suggestion_tier,
)
from teamarr.consumers.stream_match_cache import NullStreamMatchCache, StreamMatchCache
from teamarr.database import get_db, init_db
from teamarr.database.groups import create_group
from teamarr.database.source_candidates import (
    CandidateEvidence,
    ScanEvidence,
    get_candidates,
    record_scan,
    set_candidate_status,
)

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        conn.execute(
            "UPDATE sports_subscription SET leagues = ? WHERE id = 1",
            (json.dumps(["nba", "nhl", "eng.1"]),),
        )
        conn.commit()


def _group(id_, name, streams=10):
    return SimpleNamespace(id=id_, name=name, m3u_accounts=[{"stream_count": streams}])


def _stream(id_, name, stale=False):
    return SimpleNamespace(id=id_, name=name, tvg_id=None, is_stale=stale, m3u_account_id=4)


class FakeM3U:
    def __init__(self, groups, streams):
        self.groups, self.streams, self.read = groups, streams, []

    def list_groups(self):
        return self.groups

    def list_streams(self, group_id=None, limit=None, **_):
        self.read.append(group_id)
        return self.streams.get(group_id, [])


class FakeProcessor:
    """Stands in for the run's filter and matcher: 'A vs B' is a game in the
    league named before the colon, 'team:' is a team-only match."""

    def __init__(self):
        self.caches = []

    def _get_subscription_leagues(self, conn, group):
        return ["nba", "nhl", "eng.1"]

    def _filter_streams(self, streams, group):
        return streams, None

    def _match_streams(self, streams, group, today, resolved_leagues=None, cache=None):
        self.caches.append(cache)
        results = []
        for s in streams:
            league, _, rest = s["name"].partition(": ")
            if " vs " in rest:
                results.append(
                    SimpleNamespace(
                        matched=True,
                        included=True,
                        stream_id=s["id"],
                        league=league,
                        category=StreamCategory.TEAM_VS_TEAM,
                        event=SimpleNamespace(provider="espn", id=rest),
                    )
                )
            elif league == "team":
                results.append(
                    SimpleNamespace(
                        matched=True,
                        included=True,
                        stream_id=s["id"],
                        league="nba",
                        category=StreamCategory.TEAM_ONLY,
                        event=None,
                    )
                )
            else:
                results.append(
                    SimpleNamespace(matched=False, stream_id=s["id"], league=None, category=None)
                )
        return SimpleNamespace(results=results)


def _scan(groups, streams, now=NOW):
    m3u, proc = FakeM3U(groups, streams), FakeProcessor()
    summary = SourceDiscovery(get_db, SimpleNamespace(m3u=m3u), proc).scan(now=now)
    return summary, m3u, proc


def _by_name(now=NOW):
    with get_db() as conn:
        return {c.m3u_group_name: c for c in get_candidates(conn, now, 7)}


# --- the scan ---------------------------------------------------------------


def test_a_group_with_games_is_recorded_with_its_leagues(db):
    streams = {
        7: [
            _stream(1, "nhl: A vs B"),
            _stream(2, "nhl: C vs D"),
            _stream(3, "nba: E vs F"),
            _stream(4, "ESPN News"),
        ]
    }
    summary, _, _ = _scan([_group(7, "USA | ESPN Plus")], streams)
    cand = _by_name()["USA | ESPN Plus"]
    assert (cand.best_game_matches, cand.leagues) == (3, {"nhl": 2, "nba": 1})
    assert cand.m3u_account_ids == [4]
    assert summary.groups_with_games == 1


class ExcludingProcessor(FakeProcessor):
    """The matcher as it really behaves: it searches every league it knows
    and marks a hit outside the subscription matched but not included."""

    def _match_streams(self, streams, group, today, resolved_leagues=None, cache=None):
        result = super()._match_streams(streams, group, today, resolved_leagues, cache)
        for r in result.results:
            if r.matched and r.league not in resolved_leagues:
                r.included = False
                r.exclusion_reason = f"league_not_included:{r.league}"
        return result


def test_a_match_outside_the_subscription_is_not_evidence(db):
    """#1088: an NFL+NHL+NBA install saw groups suggested on NCAA soccer, EFL
    and WTA matches — hits a run would have excluded."""
    streams = {
        7: [_stream(1, "sco.1: Celtic vs Rangers"), _stream(2, "eng.2: Leeds vs Hull")],
        8: [_stream(3, "nhl: A vs B"), _stream(4, "wta: C vs D")],
    }
    m3u = FakeM3U([_group(7, "US| SOCCER PPV"), _group(8, "US| ESPN+ PPV")], streams)
    summary = SourceDiscovery(get_db, SimpleNamespace(m3u=m3u), ExcludingProcessor()).scan(now=NOW)
    cands = _by_name()
    soccer, espn = cands["US| SOCCER PPV"], cands["US| ESPN+ PPV"]
    assert (soccer.best_game_matches, soccer.leagues) == (0, {})
    assert suggestion_tier(soccer) is None
    assert (espn.best_game_matches, espn.leagues) == (1, {"nhl": 1})
    assert summary.groups_with_games == 1


class RunFilterProcessor(FakeProcessor):
    """The run's filter as a source built from games evidence applies it:
    with team matching off, the global event pattern drops a stream that has
    no 'A vs B' shape. The probe's team mode skips that filter."""

    def _filter_streams(self, streams, group):
        if group.team_streams_enabled:
            return streams, None
        return [s for s in streams if " vs " in s["name"]], None

    def _match_streams(self, streams, group, today, resolved_leagues=None, cache=None):
        # A per-driver onboard with no event shape still matches through the
        # GP-less racing path once it reaches the matcher (bead hjzo.7).
        results = []
        for s in streams:
            league, _, rest = s["name"].partition(": ")
            results.append(
                SimpleNamespace(
                    matched=True,
                    included=True,
                    stream_id=s["id"],
                    league=league,
                    category=StreamCategory.RACING_EVENT,
                    event=SimpleNamespace(provider="espn", id="gp"),
                )
            )
        return SimpleNamespace(results=results)


def test_a_match_the_run_would_filter_out_is_not_game_evidence(db):
    """#1034: three auto-added F1 onboard groups matched 16 streams a day in
    the scan and nothing in any run, because only the scan's probe let the
    GP-less onboard names past the event-pattern filter."""
    streams = {
        7: [_stream(1, "nba: VER - VERSTAPPEN ONBOARD"), _stream(2, "nba: LEC - LECLERC ONBOARD")],
        8: [_stream(3, "nba: A vs B"), _stream(4, "nba: C vs D"), _stream(5, "nba: E - F")],
    }
    m3u = FakeM3U([_group(7, "LIVE | NBA Onboards"), _group(8, "LIVE | NBA Games")], streams)
    SourceDiscovery(get_db, SimpleNamespace(m3u=m3u), RunFilterProcessor()).scan(now=NOW)
    cands = _by_name()
    onboards, games = cands["LIVE | NBA Onboards"], cands["LIVE | NBA Games"]
    assert onboards.best_game_matches == 0
    assert suggestion_tier(onboards) == TIER_NAME_ONLY  # the name still says NBA
    assert games.best_game_matches == 2  # "E - F" needed the bypass; "vs" rows did not
    assert suggestion_tier(games) == TIER_GAMES


def test_team_only_matches_are_counted_apart_and_never_as_games(db):
    streams = {7: [_stream(1, "team: Scotland"), _stream(2, "team: Wales")]}
    _scan([_group(7, "UK | Regional")], streams)
    cand = _by_name()["UK | Regional"]
    assert (cand.best_game_matches, cand.team_only_matches) == (0, 2)
    assert suggestion_tier(cand) is None


def test_stale_streams_are_not_matched(db):
    streams = {7: [_stream(1, "nhl: A vs B", stale=True), _stream(2, "nhl: C vs D")]}
    _scan([_group(7, "Sports 3")], streams)
    assert _by_name()["Sports 3"].best_game_matches == 1


def test_groups_that_are_already_sources_are_not_read(db):
    with get_db() as conn:
        create_group(conn, name="By id", leagues=[], m3u_group_id=7)
        create_group(conn, name="Disabled", leagues=[], m3u_group_id=9, enabled=False)
        conn.commit()
    groups = [_group(7, "USA | NBA"), _group(9, "Old"), _group(10, "New")]
    summary, m3u, _ = _scan(groups, {})
    assert m3u.read == [10]
    assert summary.skipped_sources == 2


def test_empty_and_dismissed_groups_are_not_read(db):
    _scan([_group(7, "Sports 9")], {7: [_stream(1, "old")]})
    with get_db() as conn:
        set_candidate_status(conn, _by_name()["Sports 9"].id, "dismissed")
    summary, m3u, _ = _scan([_group(7, "Sports 9"), _group(8, "Empty", streams=0)], {})
    assert m3u.read == []
    assert (summary.skipped_dismissed, summary.skipped_empty) == (1, 1)
    assert _by_name()["Sports 9"].status == "dismissed"


def test_a_dismissal_survives_the_group_coming_back_under_a_new_id(db):
    """A provider rename makes Dispatcharr create a new group; the "no" stands."""
    _scan([_group(7, "Sports 9")], {7: [_stream(1, "nhl: A vs B")]})
    with get_db() as conn:
        set_candidate_status(conn, _by_name()["Sports 9"].id, "dismissed")
    summary, m3u, _ = _scan([_group(70, "sports 9 ")], {70: [_stream(1, "nhl: A vs B")]})
    assert m3u.read == [] and summary.skipped_dismissed == 1
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status FROM source_candidates WHERE m3u_group_id = 70"
        ).fetchall()
    assert [r[0] for r in rows] == ["dismissed"]


def test_every_stream_is_matched_not_a_sample(db):
    streams = {7: [_stream(i, f"nhl: A{i} vs B{i}") for i in range(400)]}
    _scan([_group(7, "USA: ESPN PLUS", streams=400)], streams)
    cand = _by_name()["USA: ESPN PLUS"]
    assert cand.best_game_matches == 400 and len(cand.event_ids) == 400


def test_a_replay_group_is_recorded_but_never_matched_or_suggested(db):
    groups = [_group(7, "Replay | NBA"), _group(8, "Sports | NBA Extra")]
    streams = {
        7: [_stream(1, "nba: A vs B")],
        8: [
            _stream(2, "NBA Replay 9"),
            _stream(3, "NBA Replay Highlights"),
            _stream(4, "nba: A vs B"),
        ],
    }
    summary, _, proc = _scan(groups, streams)
    assert summary.skipped_replay == 2 and proc.caches == []
    for cand in _by_name().values():
        assert cand.replay is True and suggestion_tier(cand) is None


def test_the_scan_waits_for_a_generation_run_between_groups(db, monkeypatch):
    from teamarr.consumers import generation_status
    from teamarr.consumers.source_lifecycle import discovery as sd

    answers = iter([True, True, False])
    monkeypatch.setattr(generation_status, "is_in_progress", lambda: next(answers, False))
    naps = []
    monkeypatch.setattr(sd.time, "sleep", naps.append)
    _scan([_group(7, "Sports")], {7: [_stream(1, "nhl: A vs B")]})
    assert naps == [2, 2]


def test_the_scan_never_bumps_the_generation_counter(db):
    # A matcher built without a generation increments the counter per batch;
    # a scan did that once per group, and the next run's purge_stale then
    # dropped every cached row as stale (#1081). The scan pins the matcher to
    # the current generation instead.
    from teamarr.consumers.stream_match_cache import (
        get_generation_counter,
        increment_generation_counter,
    )

    increment_generation_counter(get_db)
    before = get_generation_counter(get_db)
    _, _, proc = _scan([_group(7, "Sports")], {7: [_stream(1, "nhl: A vs B")]})
    assert proc._generation == before
    assert get_generation_counter(get_db) == before


def test_the_scan_runs_its_matching_with_debug_quiet(db, monkeypatch):
    import threading

    from teamarr.utilities import logging as tlog

    seen = {}
    proc = FakeProcessor()
    original = proc._match_streams

    def spy(*args, **kwargs):
        seen["quiet"] = threading.get_ident() in tlog._quiet_threads
        return original(*args, **kwargs)

    proc._match_streams = spy
    m3u = FakeM3U([_group(7, "Sports")], {7: [_stream(1, "nhl: A vs B")]})
    SourceDiscovery(get_db, SimpleNamespace(m3u=m3u), proc).scan(now=NOW)
    assert seen == {"quiet": True}
    assert threading.get_ident() not in tlog._quiet_threads


def test_the_discovery_task_lets_a_same_minute_generation_start_first():
    from teamarr.consumers.scheduler import generation_due_this_minute, wait_for_generation_start

    assert generation_due_this_minute("0 * * * *", datetime(2026, 10, 17, 11, 0, 3)) is True
    assert generation_due_this_minute("0 * * * *", datetime(2026, 10, 17, 11, 1, 3)) is False
    assert generation_due_this_minute("30 2 * * *", datetime(2026, 10, 17, 11, 0, 3)) is False
    assert generation_due_this_minute("not a cron", datetime(2026, 10, 17, 11, 0, 3)) is False

    answers = iter([False, False, True])
    naps = []
    assert wait_for_generation_start(lambda: next(answers, True), naps.append) is True
    assert naps == [1, 1]
    # A generation that never starts (disabled, or skipped) does not hold the scan.
    naps = []
    assert wait_for_generation_start(lambda: False, naps.append, grace_seconds=3) is False
    assert naps == [1, 1, 1]


def test_a_group_count_the_listing_does_not_give_is_read_not_assumed_empty(db):
    old_style = SimpleNamespace(id=7, name="Sports", m3u_accounts=(4, 2))
    _, m3u, _ = _scan([old_style], {7: [_stream(1, "nhl: A vs B")]})
    assert m3u.read == [7]


def test_the_scan_never_touches_the_match_cache(db):
    _, _, proc = _scan([_group(7, "Sports")], {7: [_stream(1, "nhl: A vs B")]})
    assert all(isinstance(c, NullStreamMatchCache) for c in proc.caches) and proc.caches
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0


def test_one_unreadable_group_does_not_cost_the_rest(db):
    m3u = FakeM3U([_group(7, "Bad"), _group(8, "Good")], {8: [_stream(1, "nhl: A vs B")]})
    real = m3u.list_streams

    def flaky(group_id=None, **kw):
        if group_id == 7:
            raise RuntimeError("timeout")
        return real(group_id=group_id, **kw)

    m3u.list_streams = flaky
    summary = SourceDiscovery(get_db, SimpleNamespace(m3u=m3u), FakeProcessor()).scan(now=NOW)
    assert (summary.errors, summary.groups_scanned) == (1, 1)
    assert "Good" in _by_name()


# --- the null cache -----------------------------------------------------------


def test_the_null_cache_remembers_nothing_but_still_clears_real_failures(db):
    real = StreamMatchCache(get_db)
    real.set_failed(5, 1, "A vs B", generation=1, reason="no_event_found")
    null = NullStreamMatchCache(get_db)
    null.set_failed(5, 2, "C vs D", generation=1, reason="no_event_found")
    assert null.get(5, 1, "A vs B", include_failed=True) is None
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 1
    null.clear_failed()
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0


# --- evidence over time ---------------------------------------------------------


def _ev(games, name="Live | EPL", gid=7):
    return ScanEvidence(
        m3u_group_id=gid,
        m3u_group_name=name,
        streams_read=10,
        game_matches=games,
        leagues={"eng.1": games} if games else {},
    )


def test_a_quiet_day_does_not_erase_the_day_the_group_had_games(db):
    with get_db() as conn:
        record_scan(conn, [_ev(8)], NOW - timedelta(days=2))
        record_scan(conn, [_ev(0)], NOW)
    cand = _by_name()["Live | EPL"]
    assert (cand.scans, cand.best_game_matches, cand.days_matched) == (2, 8, 1)
    assert cand.leagues == {"eng.1": 8}


def test_evidence_older_than_the_window_stops_counting(db):
    with get_db() as conn:
        record_scan(conn, [_ev(8)], NOW - timedelta(days=9))
        record_scan(conn, [_ev(0)], NOW)
    assert _by_name()["Live | EPL"].best_game_matches == 0


def test_a_rename_is_followed_and_status_survives_a_rescan(db):
    with get_db() as conn:
        record_scan(conn, [_ev(1, name="NBA (Preseason)")], NOW - timedelta(days=1))
        cid = get_candidates(conn, NOW, 7)[0].id
        set_candidate_status(conn, cid, "accepted", source_group_id=42)
        record_scan(conn, [_ev(1, name="NBA")], NOW)
    cand = _by_name()["NBA"]
    assert (cand.status, cand.source_group_id) == ("accepted", 42)


# --- the name layer and the rule -------------------------------------------------


def test_group_names_are_read_for_league_names_as_whole_words(db):
    with get_db() as conn:
        surfaces = league_name_surfaces(conn, ["nba", "nhl", "eng.1"])
    assert leagues_named_by("USA | NBA 🏀", surfaces) == ["nba"]
    assert leagues_named_by("REPLAYS | NFL/NBA/NHL", surfaces) == ["nba", "nhl"]
    assert leagues_named_by("Live | English Premier League - EPL ⚽", surfaces) == ["eng.1"]
    assert leagues_named_by("WNBA and Unbalanced", surfaces) == []


def _cand(games=0, name_leagues=(), team_only=0):
    return CandidateEvidence(
        id=1,
        m3u_group_id=7,
        m3u_group_name="g",
        m3u_account_ids=[],
        stream_count=10,
        name_leagues=list(name_leagues),
        status="new",
        source_group_id=None,
        last_seen_at=None,
        last_matched_at=None,
        best_game_matches=games,
        team_only_matches=team_only,
    )


@pytest.mark.parametrize(
    "games, named, tier",
    [
        (3, False, TIER_GAMES),  # content alone
        (2, False, None),  # not enough without a name
        (1, True, TIER_GAMES),  # the name lowers the bar
        (0, True, TIER_NAME_ONLY),  # worth showing, never worth importing
        (0, False, None),
    ],
)
def test_the_suggestion_rule(games, named, tier):
    assert suggestion_tier(_cand(games, ["nba"] if named else [])) == tier


def test_team_only_matches_never_qualify_a_group():
    assert suggestion_tier(_cand(games=0, team_only=40)) is None


def test_team_streams_qualify_only_in_a_league_the_group_name_names():
    named = _cand(name_leagues=["nfl"])
    named.team_leagues = {"nfl": 30}
    assert suggestion_tier(named) == TIER_TEAMS
    # "UK | News" matching national teams on a country word: no league in the name
    unnamed = _cand()
    unnamed.team_leagues = {"uefa.nations": 12}
    assert suggestion_tier(unnamed) is None
    # the name says NFL, the teams matched are somewhere else
    elsewhere = _cand(name_leagues=["nfl"])
    elsewhere.team_leagues = {"uefa.nations": 12}
    assert suggestion_tier(elsewhere) == TIER_NAME_ONLY
    few = _cand(name_leagues=["nfl"])
    few.team_leagues = {"nfl": 2}
    assert suggestion_tier(few) == TIER_NAME_ONLY


@pytest.mark.parametrize(
    "group, streams, replay",
    [
        ("Replay | NBA", ["NBA Replay 9"], True),
        ("Sports | EPL Replays", [], True),
        ("Sports 4", ["NHL Replay info", "NHL Replay Highlights", "NHL Replay 9", "Info"], True),
        ("USA | NBA", ["NBA 01: Lakers vs Celtics", "NBA 02: Replay of the night"], True),
        (
            "USA | NBA",
            ["NBA 01: Lakers vs Celtics", "NBA 02: Suns vs Kings", "NBA 03: Replay"],
            False,
        ),
        ("Instant Replayers FC", ["A vs B"], False),
        ("USA | NBA", [], False),
    ],
)
def test_replay_groups_are_told_by_their_own_words(group, streams, replay):
    assert is_replay_group(group, streams) is replay


def test_a_name_only_group_with_streams_all_week_and_no_match_drops_off(db):
    def ev(read):
        return ScanEvidence(
            m3u_group_id=7,
            m3u_group_name="Sports | NBA Classics",
            streams_read=read,
            name_leagues=["nba"],
        )

    with get_db() as conn:
        for day in range(6, -1, -1):
            record_scan(conn, [ev(12)], NOW - timedelta(days=day, hours=1))
    assert suggestion_tier(_by_name()["Sports | NBA Classics"]) is None


def test_a_name_only_group_that_was_empty_some_days_is_still_waiting(db):
    with get_db() as conn:
        for day in range(6, -1, -1):
            record_scan(
                conn,
                [
                    ScanEvidence(
                        m3u_group_id=7,
                        m3u_group_name="LIVE | EPL (Sat)",
                        streams_read=0 if day % 2 else 12,
                        name_leagues=["eng.1"],
                    )
                ],
                NOW - timedelta(days=day, hours=1),
            )
    assert suggestion_tier(_by_name()["LIVE | EPL (Sat)"]) == TIER_NAME_ONLY


def test_several_scans_in_one_day_are_one_day_of_evidence(db):
    with get_db() as conn:
        for hour in range(8):
            record_scan(
                conn,
                [
                    ScanEvidence(
                        m3u_group_id=7,
                        m3u_group_name="Sports | NBA Extra",
                        streams_read=12,
                        name_leagues=["nba"],
                    )
                ],
                NOW - timedelta(hours=hour),
            )
    cand = _by_name()["Sports | NBA Extra"]
    assert cand.scan_days <= 2 and suggestion_tier(cand) == TIER_NAME_ONLY


def test_groups_with_the_same_events_fold_into_one_suggestion():
    def cand(id_, name, events):
        c = _cand(games=len(events))
        c.id, c.m3u_group_name, c.event_ids = id_, name, set(events)
        return c

    a = cand(1, "CAN: TSN+", [f"e{i}" for i in range(10)])
    b = cand(2, "Sports | TSN+ (2)", [f"e{i}" for i in range(9)])  # 9 of 10 shared
    c = cand(3, "Sports | F1", [f"e{i}" for i in range(4)])  # too little shared
    d = cand(4, "LIVE | EPL (Sat)", [])  # nothing matched
    e = cand(5, "Sports | EPL Teams", [])
    # one shared event is a race week, not the same content
    f = cand(6, "Live | F1 TV", ["gp"])
    g = cand(7, "Live | Apple TV F1", ["gp"])
    folded = fold_same_content([d, c, b, a, e, f, g])
    assert [[x.m3u_group_name for x in grp] for grp in folded] == [
        ["CAN: TSN+", "Sports | TSN+ (2)"],
        ["Sports | F1"],
        ["Live | Apple TV F1"],
        ["Live | F1 TV"],
        ["LIVE | EPL (Sat)"],
        ["Sports | EPL Teams"],
    ]


# --- API and schedule -------------------------------------------------------------


@pytest.fixture()
def api(db):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    return TestClient(app)


def _seed(now=None):
    from teamarr.utilities.tz import now_utc

    now = now or now_utc()
    with get_db() as conn:
        record_scan(
            conn,
            [
                ScanEvidence(
                    m3u_group_id=1,
                    m3u_group_name="USA: ESPN PLUS",
                    streams_read=50,
                    game_matches=9,
                    leagues={"nhl": 9},
                    event_ids={f"espn:{i}" for i in range(9)},
                ),
                ScanEvidence(
                    m3u_group_id=2,
                    m3u_group_name="Sports | NBA Extra",
                    streams_read=19,
                    name_leagues=["nba"],
                ),
                ScanEvidence(
                    m3u_group_id=5, m3u_group_name="Replay | NBA", name_leagues=["nba"], replay=True
                ),
                ScanEvidence(
                    m3u_group_id=6,
                    m3u_group_name="USA | NFL Teams",
                    streams_read=34,
                    team_only_matches=30,
                    team_leagues={"nfl": 30},
                    name_leagues=["nfl"],
                ),
                ScanEvidence(
                    m3u_group_id=8,
                    m3u_group_name="Sports | ESPN PLUS (2)",
                    streams_read=50,
                    game_matches=9,
                    leagues={"nhl": 9},
                    event_ids={f"espn:{i}" for i in range(9)},
                ),
                ScanEvidence(
                    m3u_group_id=3, m3u_group_name="UK | News", streams_read=50, team_only_matches=5
                ),
                ScanEvidence(
                    m3u_group_id=4,
                    m3u_group_name="LIVE | NBA (Preseason)",
                    streams_read=14,
                    game_matches=2,
                    leagues={"nba": 2},
                    name_leagues=["nba"],
                ),
            ],
            now,
        )


def test_the_review_list_holds_only_groups_worth_suggesting_strongest_first(api):
    _seed()
    body = api.get("/api/v1/source-discovery/candidates").json()
    assert [(c["m3u_group_name"], c["tier"]) for c in body["candidates"]] == [
        ("Sports | ESPN PLUS (2)", "games"),
        ("USA: ESPN PLUS", "games"),
        ("LIVE | NBA (Preseason)", "games"),
        ("USA | NFL Teams", "teams"),
        ("Sports | NBA Extra", "name_only"),
    ]
    by_name = {c["m3u_group_name"]: c for c in body["candidates"]}
    assert by_name["USA: ESPN PLUS"]["same_events_as"] == "Sports | ESPN PLUS (2)"
    assert by_name["Sports | ESPN PLUS (2)"]["same_events_as"] is None
    assert by_name["Sports | ESPN PLUS (2)"]["events"] == 9
    assert by_name["USA | NFL Teams"]["team_leagues"] == {"nfl": 30}
    assert body["window_days"] == 7 and body["scan"]["running"] is False


def test_a_dismissed_candidate_leaves_the_list_and_can_be_restored(api):
    _seed()
    cid = api.get("/api/v1/source-discovery/candidates").json()["candidates"][4]["id"]
    assert api.post(f"/api/v1/source-discovery/candidates/{cid}/dismiss").status_code == 200
    names = lambda **p: [  # noqa: E731
        c["m3u_group_name"]
        for c in api.get("/api/v1/source-discovery/candidates", params=p).json()["candidates"]
    ]
    assert "Sports | NBA Extra" not in names()
    assert "Sports | NBA Extra" in names(include_dismissed=True)
    api.post(f"/api/v1/source-discovery/candidates/{cid}/restore")
    assert "Sports | NBA Extra" in names()
    assert api.post("/api/v1/source-discovery/candidates/9999/dismiss").status_code == 404


def test_the_scan_is_on_by_default_and_the_only_control_is_the_switch(api):
    """#1027: the scan runs once a day at a fixed hour; no cron to set."""
    got = api.get("/api/v1/settings/scheduler").json()
    assert got["source_discovery_mode"] == "suggest"
    assert "source_discovery_cron" not in got
    off = api.put("/api/v1/settings/scheduler", json={"source_discovery_mode": "off"})
    assert off.status_code == 200
    assert off.json()["source_discovery_mode"] == "off"
    on = api.put("/api/v1/settings/scheduler", json={"source_discovery_mode": "suggest"})
    assert on.json()["source_discovery_mode"] == "suggest"
    assert (
        api.put(
            "/api/v1/settings/scheduler", json={"source_discovery_mode": "sometimes"}
        ).status_code
        == 422
    )


def test_a_scan_is_skipped_without_dispatcharr_and_only_one_runs_at_a_time(db, monkeypatch):
    from teamarr.consumers.source_lifecycle import discovery as sd

    monkeypatch.setattr(
        "teamarr.dispatcharr.factory.get_dispatcharr_connection", lambda *a, **k: None
    )
    assert sd.run_discovery_scan(get_db)["skipped"] is True
    assert sd.discovery_status()["running"] is False
    assert sd._scan_lock.acquire(blocking=False)
    try:
        assert "already running" in sd.run_discovery_scan(get_db)["reason"]
    finally:
        sd._scan_lock.release()


# --- managed sources ---------------------------------------------------------------


def _accept_first(api):
    _seed()
    listed = api.get("/api/v1/source-discovery/candidates").json()["candidates"]
    cid = next(c["id"] for c in listed if c["m3u_group_name"] == "USA: ESPN PLUS")  # group 1
    resp = api.post(f"/api/v1/source-discovery/candidates/{cid}/accept")
    assert resp.status_code == 201, resp.text
    return cid, resp.json()["source_group_id"]


def _source(source_id):
    from teamarr.database.groups import get_group

    with get_db() as conn:
        return get_group(conn, source_id)


def _backdate(source_id, **cols):
    with get_db() as conn:
        for col, days in cols.items():
            conn.execute(
                f"UPDATE event_epg_groups SET {col} = datetime('now', ?) WHERE id = ?",
                (f"-{days} days", source_id),
            )
        conn.commit()


def _maintain(live=(1,), evidence=None):
    from teamarr.consumers.source_lifecycle.discovery import ScanSummary, maintain_managed_sources
    from teamarr.utilities.tz import now_utc

    summary = ScanSummary()
    with get_db() as conn:
        # Callers key their evidence by group; the scan keys it by group and account.
        keyed = {(e.m3u_group_id, e.m3u_account_id or 0): e for e in (evidence or {}).values()}
        maintain_managed_sources(conn, now_utc(), set(live), keyed, summary)
    return summary


def test_accepting_a_candidate_creates_a_managed_source(api):
    cid, source_id = _accept_first(api)
    source = _source(source_id)
    assert (source.name, source.m3u_group_id, source.managed, source.enabled) == (
        "USA: ESPN PLUS",
        1,
        True,
        True,
    )
    listed = api.get("/api/v1/groups").json()["groups"]
    assert next(g for g in listed if g["id"] == source_id)["managed"] is True
    names = [
        c["m3u_group_name"]
        for c in api.get("/api/v1/source-discovery/candidates").json()["candidates"]
    ]
    assert "USA: ESPN PLUS" not in names
    assert api.post(f"/api/v1/source-discovery/candidates/{cid}/accept").status_code == 409


def test_a_hand_edit_leaves_a_managed_source_automated(api):
    # The Automate switch is the one control over ``managed`` (#1079); editing
    # the subscription override no longer silently hands the source back.
    _, source_id = _accept_first(api)
    assert (
        api.put(f"/api/v1/groups/{source_id}", json={"subscription_leagues": ["nhl"]}).status_code
        == 200
    )
    assert _source(source_id).managed is True


def test_the_automate_switch_hands_a_source_back_and_over(api):
    _, source_id = _accept_first(api)
    assert api.put(f"/api/v1/groups/{source_id}", json={"managed": False}).status_code == 200
    assert _source(source_id).managed is False
    assert api.put(f"/api/v1/groups/{source_id}", json={"managed": True}).status_code == 200
    assert _source(source_id).managed is True


def test_changing_enabled_through_the_form_takes_the_source_back(api):
    _, source_id = _accept_first(api)
    # The form sends the whole row back; the same enabled state is not a hand switch.
    assert api.put(f"/api/v1/groups/{source_id}", json={"enabled": True}).status_code == 200
    assert _source(source_id).managed is True
    assert api.put(f"/api/v1/groups/{source_id}", json={"enabled": False}).status_code == 200
    assert _source(source_id).managed is False


def test_automate_on_a_manually_imported_source_writes_its_candidate_row(api):
    from teamarr.database.groups import create_group

    with get_db() as conn:
        source_id = create_group(
            conn,
            name="Live | FA Cup",
            leagues=[],
            m3u_group_id=77,
            m3u_group_name="UK: NHL Centre Ice",
        )
    assert _source(source_id).managed is False
    resp = api.put(f"/api/v1/groups/{source_id}", json={"managed": True})
    assert resp.status_code == 200, resp.text
    source = _source(source_id)
    assert source.managed is True
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, source_group_id, name_leagues FROM source_candidates "
            "WHERE m3u_group_id = 77"
        ).fetchone()
    assert (row["status"], row["source_group_id"]) == ("accepted", source_id)
    assert json.loads(row["name_leagues"]) == ["nhl"]
    # Automated and enabled: the scan treats its group as taken, like any source.
    listed = api.get("/api/v1/groups").json()["groups"]
    assert next(g for g in listed if g["id"] == source_id)["managed"] is True


def test_automate_needs_stream_name_or_team_matching(api):
    from teamarr.database.groups import create_group

    with get_db() as conn:
        source_id = create_group(
            conn,
            name="UK: Sky Sports Main Event",
            leagues=[],
            m3u_group_id=78,
            name_match_enabled=False,
            epg_match_enabled=True,
        )
    resp = api.put(f"/api/v1/groups/{source_id}", json={"managed": True})
    assert resp.status_code == 400
    assert "Stream name or Team" in resp.json()["detail"]
    # ... and an automated source edited down to EPG-only is handed back, since
    # Automation could never switch it on again.
    _, managed_id = _accept_first(api)
    resp = api.put(
        f"/api/v1/groups/{managed_id}",
        json={
            "name_match_enabled": False,
            "team_streams_enabled": False,
            "epg_match_enabled": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert _source(managed_id).managed is False


def test_bulk_edit_sets_the_automate_switch(api):
    from teamarr.database.groups import create_group

    with get_db() as conn:
        a = create_group(conn, name="A", leagues=[], m3u_group_id=81)
        b = create_group(conn, name="B", leagues=[], m3u_group_id=82)
    resp = api.put("/api/v1/groups/bulk", json={"group_ids": [a, b], "managed": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_updated"] == 2
    assert (_source(a).managed, _source(b).managed) == (True, True)
    resp = api.put("/api/v1/groups/bulk", json={"group_ids": [a], "managed": False})
    assert resp.status_code == 200
    assert (_source(a).managed, _source(b).managed) == (False, True)


def test_team_streams_in_a_named_league_wake_a_retired_source(api):
    # The revive rule reads the same evidence discovery accepts for a
    # team-stream source: one-team matches in a league the group's name names.
    _, source_id = _accept_first(api)
    with get_db() as conn:
        conn.execute("UPDATE event_epg_groups SET enabled = 0 WHERE id = ?", (source_id,))
        conn.commit()
    summary = _maintain(
        evidence={
            1: ScanEvidence(
                1,
                "NHL: ESPN PLUS",
                team_only_matches=4,
                team_leagues={"nhl": 4},
                name_leagues=["nhl"],
            )
        }
    )
    assert (summary.sources_reenabled, _source(source_id).enabled) == (1, True)
    with get_db() as conn:
        conn.execute("UPDATE event_epg_groups SET enabled = 0 WHERE id = ?", (source_id,))
        conn.commit()
    # Team matches in a league the name does not mention are noise, as in discovery.
    summary = _maintain(
        evidence={
            1: ScanEvidence(1, "USA: ESPN PLUS", team_only_matches=4, team_leagues={"nhl": 4})
        }
    )
    assert (summary.sources_reenabled, _source(source_id).enabled) == (0, False)


def test_disabling_by_hand_also_claims_it_so_discovery_never_turns_it_back_on(api):
    _, source_id = _accept_first(api)
    assert api.post(f"/api/v1/groups/{source_id}/disable").status_code == 200
    summary = _maintain(evidence={1: ScanEvidence(1, "USA: ESPN PLUS", game_matches=9)})
    source = _source(source_id)
    assert (source.managed, source.enabled, summary.sources_reenabled) == (False, False, 0)


def test_the_idle_window_is_the_policy_setting(api):
    # Sources → Automation → Retire (#1058): the days are a setting, not a constant.
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=2)
    assert _maintain().sources_disabled == 0
    with get_db() as conn:
        conn.execute("UPDATE settings SET source_idle_days = 1")
        conn.commit()
    assert _maintain().sources_disabled == 1
    assert _source(source_id).enabled is False


def test_an_idle_managed_source_is_disabled_and_comes_back_with_games(api):
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=15)
    assert _maintain().sources_disabled == 1
    source = _source(source_id)
    assert (source.enabled, source.managed) == (False, True)
    assert _maintain(evidence={1: ScanEvidence(1, "USA: ESPN PLUS")}).sources_reenabled == 0
    again = _maintain(evidence={1: ScanEvidence(1, "USA: ESPN PLUS", game_matches=2)})
    assert again.sources_reenabled == 1 and _source(source_id).enabled is True


def test_a_recent_match_keeps_a_managed_source(api):
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=40, last_matched_at=3)
    assert _maintain().sources_disabled == 0


def test_a_hand_made_source_is_never_touched_however_idle(api):
    with get_db() as conn:
        source_id = create_group(conn, name="Mine", leagues=[], m3u_group_id=77)
        conn.commit()
    _backdate(source_id, created_at=400)
    summary = _maintain(live=())
    assert (summary.sources_disabled, summary.sources_removed) == (0, 0)
    assert _source(source_id).enabled is True


def test_a_retired_source_is_removed_only_once_its_group_has_been_gone_long_enough(api):
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=15)
    _maintain(live=())  # idle -> disabled
    assert _maintain(live=()).sources_removed == 1  # created 15 days ago, group gone
    assert _source(source_id) is None


def test_a_retired_source_whose_group_still_exists_is_kept(api):
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=60)
    _maintain()
    assert _maintain().sources_removed == 0
    assert _source(source_id).enabled is False


def test_gone_is_counted_from_the_last_scan_that_saw_the_group(api):
    """Retired long ago, group vanished yesterday: not removed yet."""
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=60)
    _maintain()  # disabled
    _maintain()  # still listed: last seen is now
    assert _maintain(live=()).sources_removed == 0
    _backdate(source_id, source_last_seen=15)
    assert _maintain(live=()).sources_removed == 1


def test_a_retired_managed_sources_group_is_scanned_again(api):
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=15)
    _maintain()
    summary, m3u, _ = _scan([_group(1, "USA: ESPN PLUS")], {1: [_stream(1, "nhl: A vs B")]})
    assert m3u.read == [1] and summary.sources_reenabled == 1
    assert _source(source_id).enabled is True


def test_a_run_that_matches_stamps_the_source(db):
    from teamarr.database.groups import get_group, update_group_stats

    with get_db() as conn:
        source_id = create_group(conn, name="S", leagues=[], m3u_group_id=5)
        update_group_stats(conn, source_id, stream_count=10, matched_count=0)
        assert get_group(conn, source_id).last_matched_at is None
        update_group_stats(conn, source_id, stream_count=10, matched_count=4)
        assert get_group(conn, source_id).last_matched_at is not None


def test_a_team_stream_group_becomes_a_team_stream_source(api):
    _seed()
    listed = api.get("/api/v1/source-discovery/candidates").json()["candidates"]
    cid = next(c["id"] for c in listed if c["tier"] == "teams")
    source_id = api.post(f"/api/v1/source-discovery/candidates/{cid}/accept").json()[
        "source_group_id"
    ]
    source = _source(source_id)
    assert (source.team_streams_enabled, source.name_match_enabled) == (True, False)


def test_deleting_an_accepted_source_by_hand_is_a_dismissal(api):
    cid, source_id = _accept_first(api)
    assert api.delete(f"/api/v1/groups/{source_id}").status_code == 200
    names = [
        c["m3u_group_name"]
        for c in api.get(
            "/api/v1/source-discovery/candidates", params={"include_dismissed": True}
        ).json()["candidates"]
        if c["status"] == "dismissed"
    ]
    assert names == ["USA: ESPN PLUS"]
    # ... and a scan that sees games in it does not bring it back
    summary, m3u, _ = _scan([_group(1, "USA: ESPN PLUS")], {1: [_stream(1, "nhl: A vs B")]})
    assert m3u.read == [] and summary.sources_readded == 0


def test_a_removed_managed_source_is_added_back_when_its_group_returns(api):
    """Approved once: the user is not asked again."""
    _, source_id = _accept_first(api)
    _backdate(source_id, created_at=15)
    _maintain(live=())
    assert _maintain(live=()).sources_removed == 1
    streams = {1: [_stream(i, f"nhl: A{i} vs B{i}") for i in range(4)]}
    summary, _, _ = _scan([_group(1, "USA: ESPN PLUS")], streams)
    assert summary.sources_readded == 1
    with get_db() as conn:
        row = conn.execute(
            "SELECT managed, enabled, m3u_group_id FROM event_epg_groups "
            "WHERE name = 'USA: ESPN PLUS'"
        ).fetchone()
    assert tuple(row) == (1, 1, 1)


def test_the_list_is_flat_and_ordered_by_m3u_account(api, monkeypatch):
    from teamarr.utilities.tz import now_utc

    monkeypatch.setattr(
        "teamarr.api.routes.source_discovery._account_names", lambda: {4: "Onyx", 2: "Aura"}
    )
    with get_db() as conn:
        record_scan(
            conn,
            [
                ScanEvidence(
                    m3u_group_id=1,
                    m3u_group_name="LIVE | NHL",
                    m3u_account_ids=[4],
                    game_matches=3,
                    leagues={"nhl": 3},
                ),
                ScanEvidence(
                    m3u_group_id=2,
                    m3u_group_name="Sports | NHL",
                    m3u_account_ids=[2],
                    streams_read=5,
                    name_leagues=["nhl"],
                ),
                ScanEvidence(
                    m3u_group_id=3,
                    m3u_group_name="LIVE | ESPN+",
                    m3u_account_ids=[4],
                    game_matches=40,
                    leagues={"nhl": 40},
                ),
                ScanEvidence(
                    m3u_group_id=4,
                    m3u_group_name="Sports | F1",
                    m3u_account_ids=[9],
                    game_matches=5,
                    leagues={"f1": 5},
                ),
            ],
            now_utc(),
        )
    rows = api.get("/api/v1/source-discovery/candidates").json()["candidates"]
    assert [(r["m3u_account_name"], r["m3u_group_name"]) for r in rows] == [
        ("Account 9", "Sports | F1"),
        ("Aura", "Sports | NHL"),
        ("Onyx", "LIVE | ESPN+"),
        ("Onyx", "LIVE | NHL"),
    ]
    assert all("alternates" not in r for r in rows)


# --- automatic mode -------------------------------------------------------------------


def _toggle(leagues=(), sports=()):
    from teamarr.database.subscription import update_subscription

    with get_db() as conn:
        update_subscription(
            conn, auto_source_leagues=list(leagues), auto_source_sports=list(sports)
        )


def _two_days(gid, name, games, leagues, streams=50, name_leagues=(), team=0, team_leagues=None):
    from teamarr.utilities.tz import now_utc

    with get_db() as conn:
        for day in (1, 0):
            record_scan(
                conn,
                [
                    ScanEvidence(
                        m3u_group_id=gid,
                        m3u_group_name=name,
                        stream_count=streams,
                        streams_read=streams,
                        game_matches=games,
                        leagues=dict(leagues),
                        name_leagues=list(name_leagues),
                        team_only_matches=team,
                        team_leagues=dict(team_leagues or {}),
                    )
                ],
                now_utc() - timedelta(days=day),
            )


def _auto(summary_only=False):
    from teamarr.consumers.source_lifecycle.discovery import ScanSummary, auto_add_sources
    from teamarr.utilities.tz import now_utc

    summary = ScanSummary()
    with get_db() as conn:
        auto_add_sources(conn, now_utc(), summary)
    return summary


def _sources():
    with get_db() as conn:
        return {
            r[0]: r
            for r in conn.execute(
                "SELECT name, managed, auto_added_at, team_streams_enabled, name_match_enabled "
                "FROM event_epg_groups"
            )
        }


def test_nothing_is_added_while_no_league_is_set_to_automatic(db):
    _two_days(1, "LIVE | ESPN+", 160, {"nhl": 160})
    assert _auto().sources_auto_added == 0 and _sources() == {}


def test_a_toggled_league_adds_a_group_whose_evidence_points_at_it(db):
    _toggle(leagues=["nhl"])
    _two_days(1, "LIVE | ESPN+", 200, {"nhl": 164, "college-football": 20, "nfl": 10})
    _two_days(
        2, "USA | NFL Teams Backup", 0, {}, name_leagues=["nfl"], team=30, team_leagues={"nfl": 30}
    )
    _two_days(3, "UK: CUP GAMES", 14, {"uefa.nations": 14})
    assert _auto().sources_auto_added == 1
    src = _sources()
    assert list(src) == ["LIVE | ESPN+"]
    assert src["LIVE | ESPN+"][1] == 1 and src["LIVE | ESPN+"][2] is not None


def test_rotating_groups_share_evidence_but_same_day_variants_only_count_once(db):
    _toggle(leagues=["nhl"])
    wed, thu = _group(71, "LIVE | NHL (Wed)"), _group(72, "LIVE | NHL (Thur)")
    games = {g.id: [_stream(g.id, "nhl: A vs B")] for g in [wed, thu]}

    first, _, _ = _scan([wed, thu], games)
    (candidate,) = _by_name().values()
    assert candidate.evidence_days == 1
    assert first.sources_auto_added == 0

    later = NOW + timedelta(days=1)
    second, _, _ = _scan([wed], games, now=later)
    (current,) = _by_name(later).values()
    assert (current.id, current.m3u_group_id, current.evidence_days) == (candidate.id, wed.id, 2)
    assert second.sources_auto_added == 1
    assert current.status == "accepted"


def test_a_dismissed_day_blocks_its_own_name_not_the_family(db):
    """Dismissing `(Wed)` says no to `(Wed)`, under any id, and to nothing else (#1265)."""
    wed, thu = _group(71, "LIVE | NHL (Wed)"), _group(72, "LIVE | NHL (Thur)")
    games = {gid: [_stream(gid, "nhl: A vs B")] for gid in (71, 72, 73)}
    _scan([wed], games)
    candidate = _by_name()[wed.name]
    with get_db() as conn:
        set_candidate_status(conn, candidate.id, "dismissed")

    # Next week's (Wed) has a new id; (Thur) is another day of the family.
    wed_again = _group(73, "LIVE | NHL (Wed)")
    later = NOW + timedelta(days=1)
    for _ in range(2):  # a second scan must not fold the dismissal away
        summary, m3u, _ = _scan([wed_again, thu], games, now=later)
        assert m3u.read == [72] and summary.skipped_dismissed == 1
        found = _by_name(later)
        assert set(found) == {wed.name, thu.name}
        assert (found[wed.name].id, found[wed.name].status) == (candidate.id, "dismissed")
        assert found[wed.name].m3u_group_id == 71  # no row per new id
        assert found[thu.name].status == "new" and found[thu.name].id != candidate.id

    # Restored, the days are one family again and share one candidate.
    with get_db() as conn:
        set_candidate_status(conn, candidate.id, "new")
    _scan([wed_again, thu], games, now=later)
    (merged,) = _by_name(later).values()
    assert merged.id == candidate.id and merged.status == "new"


def _acct_stream(stream_id, name, account_id):
    stream = _stream(stream_id, name)
    stream.m3u_account_id = account_id
    return stream


@pytest.mark.parametrize("dismissed_account, read", [(4, [5]), (0, []), (5, [4])])
def test_a_dismissed_day_is_scoped_to_its_account(db, dismissed_account, read):
    """Per account (#1226); one recorded with no account covers every account."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO source_candidates (m3u_group_id, m3u_group_name, m3u_account_id, status) "
            "VALUES (60, ' live | nhl (sat)', ?, 'dismissed')",
            (dismissed_account,),
        )
    sat = SimpleNamespace(id=71, name="LIVE | NHL (Sat)", m3u_accounts=[4, 5])
    streams = {71: [_acct_stream(1, "nhl: A vs B", 4), _acct_stream(2, "nhl: A vs B", 5)]}
    _scan([sat], streams)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m3u_account_id FROM source_candidates WHERE m3u_group_id = 71 "
            "ORDER BY m3u_account_id"
        ).fetchall()
    assert [r[0] for r in rows] == read


def _managed_source(conn, name, group_id, group_name, account=4, managed=1, enabled=True):
    source_id = create_group(
        conn,
        name=name,
        leagues=[],
        m3u_group_id=group_id,
        m3u_group_name=group_name,
        m3u_account_id=account,
        enabled=enabled,
    )
    conn.execute("UPDATE event_epg_groups SET managed = ? WHERE id = ?", (managed, source_id))
    if managed:
        conn.execute(
            "INSERT INTO source_candidates "
            "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
            "VALUES (?, ?, ?, 'accepted', ?)",
            (group_id, group_name, account or 0, source_id),
        )
    return source_id


def _bound(conn):
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT name, m3u_group_id, m3u_group_name FROM event_epg_groups ORDER BY id"
        )
    ]


def _day(group_id, name, account=4, streams=10, games=1):
    return ScanEvidence(
        m3u_group_id=group_id,
        m3u_group_name=name,
        m3u_account_id=account,
        stream_count=streams,
        game_matches=games,
    )


def _rebind(conn, evidence, live_ids):
    from teamarr.consumers.source_lifecycle.discovery import ScanSummary, rebind_rotating_sources

    summary = ScanSummary()
    rebind_rotating_sources(conn, NOW, live_ids=live_ids, evidence=evidence, summary=summary)
    return summary.sources_rebound


@pytest.mark.parametrize(
    "second",
    [
        {"managed": 1},
        {"managed": 0},
        {"managed": 1, "enabled": False},
        {"managed": 0, "enabled": False},
    ],
)
def test_a_family_with_a_source_per_day_is_never_rebound(db, second):
    """More than one source of a family on an account: each stays on its own id (#1265).

    The second source counts whatever it is — hand-made, retired — because its
    existence is what says the days were kept apart on purpose.
    """
    with get_db() as conn:
        _managed_source(conn, "EPL Mon", 10, "LIVE | EPL (Mon)")
        _managed_source(conn, "EPL Fri", 11, "LIVE | EPL (Fri)", **second)
        before = _bound(conn)
        evidence = [_day(50, "LIVE | EPL (Fri)"), _day(51, "LIVE | EPL (Tue)")]
        assert _rebind(conn, evidence, {50, 51}) == 0
        assert _bound(conn) == before


def test_a_source_per_day_family_gets_other_days_as_their_own_suggestion(db):
    """The whole scan: nothing is rebound, and a day no source is named for is offered."""
    with get_db() as conn:
        _managed_source(conn, "EPL Mon", 10, "LIVE | EPL (Mon)")
        _managed_source(conn, "EPL Fri", 11, "LIVE | EPL (Fri)")
    tue = _group(51, "LIVE | EPL (Tue)")
    summary, _, _ = _scan([tue], {51: [_stream(1, "eng.1: A vs B")]})
    assert summary.sources_rebound == 0
    with get_db() as conn:
        assert [b[1] for b in _bound(conn)] == [10, 11]
    found = _by_name()
    assert (found[tue.name].status, found[tue.name].source_group_id) == ("new", None)


def test_one_account_with_a_source_per_day_does_not_stop_another_accounts_rotation(db):
    with get_db() as conn:
        _managed_source(conn, "EPL Mon 4", 10, "LIVE | EPL (Mon)", account=4)
        _managed_source(conn, "EPL Fri 4", 11, "LIVE | EPL (Fri)", account=4)
        _managed_source(conn, "EPL 5", 12, "LIVE | EPL (Mon)", account=5)
        evidence = [
            _day(50, "LIVE | EPL (Tue)", account=4),
            _day(50, "LIVE | EPL (Tue)", account=5),
        ]
        assert _rebind(conn, evidence, {50}) == 1
        assert [b[1] for b in _bound(conn)] == [10, 11, 50]


@pytest.mark.parametrize(
    "dismissed_account, rebound_to",
    [(4, 12), (0, 12), (5, 90)],
)
def test_a_rebind_never_lands_on_a_dismissed_day(db, dismissed_account, rebound_to):
    """`(Sat)` was dismissed under an old id; it returns under a new one (#1265).

    The name is what the user said no to. Another account's dismissal is not
    this account's.
    """
    with get_db() as conn:
        _managed_source(conn, "NHL", 12, "LIVE | NHL (Thur)")
        conn.execute(
            "INSERT INTO source_candidates (m3u_group_id, m3u_group_name, m3u_account_id, status) "
            "VALUES (60, 'live | NHL (Sat) ', ?, 'dismissed')",
            (dismissed_account,),
        )
        assert _rebind(conn, [_day(90, "LIVE | NHL (Sat)", streams=50)], {90}) == (rebound_to == 90)
        assert [b[1] for b in _bound(conn)] == [rebound_to]
        statuses = conn.execute(
            "SELECT m3u_group_id, status FROM source_candidates ORDER BY m3u_group_id"
        ).fetchall()
        assert (60, "dismissed") in [tuple(r) for r in statuses]


def test_a_rebind_takes_the_next_day_when_the_best_one_is_dismissed(db):
    with get_db() as conn:
        _managed_source(conn, "NHL", 12, "LIVE | NHL (Thur)")
        conn.execute(
            "INSERT INTO source_candidates (m3u_group_id, m3u_group_name, m3u_account_id, status) "
            "VALUES (60, 'LIVE | NHL (Sat)', 4, 'dismissed')"
        )
        evidence = [
            _day(90, "LIVE | NHL (Sat)", streams=50),
            _day(85, "LIVE | NHL (Fri)", streams=5),
        ]
        assert _rebind(conn, evidence, {85, 90}) == 1
        assert _bound(conn) == [("NHL", 85, "LIVE | NHL (Fri)")]


def test_a_rebind_does_not_depend_on_row_or_evidence_order(db):
    """Same inputs, any order, same binding; a rerun changes nothing."""
    import itertools

    evidence = [
        _day(81, "LIVE | NHL (Fri)", streams=10),
        _day(82, "LIVE | NHL (Sat)", streams=10),
        _day(83, "LIVE | NHL (Sun)", streams=10, games=0),
        _day(84, "LIVE | NBA (Sat)", streams=99),
    ]
    results = set()
    for order in itertools.permutations(evidence):
        with get_db() as conn:
            conn.execute("DELETE FROM source_candidates")
            conn.execute("DELETE FROM event_epg_groups")
            _managed_source(conn, "NHL", 12, "LIVE | NHL (Thur)")
            _managed_source(conn, "NBA", 13, "LIVE | NBA (Thur)")
            assert _rebind(conn, list(order), {81, 82, 83, 84}) == 2
            first = tuple(_bound(conn))
            assert _rebind(conn, list(order), {81, 82, 83, 84}) == 0
            assert tuple(_bound(conn)) == first
            results.add(first)
    assert results == {(("NHL", 82, "LIVE | NHL (Sat)"), ("NBA", 84, "LIVE | NBA (Sat)"))}


def test_a_hand_made_source_is_not_rebound_even_alone_in_its_family(db):
    with get_db() as conn:
        _managed_source(conn, "My NHL", 12, "LIVE | NHL (Thur)", managed=0)
        assert _rebind(conn, [_day(90, "LIVE | NHL (Fri)")], {90}) == 0
        assert _bound(conn) == [("My NHL", 12, "LIVE | NHL (Thur)")]


@pytest.mark.parametrize(
    "source, read, bound_to",
    [
        ({}, [5], 71),  # enabled: the per-run pass will heal it; only account 5 is news
        ({"managed": 0}, [5], 71),
        ({"account": None}, [], 71),  # no account: it reads the whole group
        # Retired: the per-run pass skips it, so its group is scanned as before
        # and the scan itself follows it there.
        ({"enabled": False}, [4, 5], 73),
    ],
)
def test_the_scan_leaves_a_returned_group_to_the_source_named_for_it(db, source, read, bound_to):
    """A scan ahead of the per-run pass must not offer a source its own group (#1265).

    The source's id is gone and its exact name is back under a new one. Read
    as a candidate, automatic mode could add a second source there and the
    heal would then be refused for good.
    """
    with get_db() as conn:
        _managed_source(conn, "NHL", 71, "LIVE | NHL (Wed)", **source)
    back = SimpleNamespace(id=73, name="LIVE | NHL (Wed)", m3u_accounts=[4, 5])
    streams = {73: [_acct_stream(1, "nhl: A vs B", 4), _acct_stream(2, "nhl: A vs B", 5)]}
    _scan([back], streams)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m3u_account_id FROM source_candidates WHERE m3u_group_id = 73 "
            "ORDER BY m3u_account_id"
        ).fetchall()
        bound = conn.execute("SELECT m3u_group_id FROM event_epg_groups").fetchone()[0]
    assert [r[0] for r in rows] == read
    assert bound == bound_to


def test_managed_source_follows_rotation_after_a_gap_and_keeps_its_settings(db):
    _toggle(leagues=["nhl"])
    first = _group(71, "LIVE | NHL (Wed)")
    _scan([first], {71: [_stream(1, "nhl: A vs B")]}, now=NOW - timedelta(days=1))
    _scan([first], {71: [_stream(1, "nhl: A vs B")]})
    candidate = _by_name()[first.name]
    source_id = candidate.source_group_id
    with get_db() as conn:
        conn.execute(
            "UPDATE event_epg_groups SET source_missing = 1, name = 'My NHL', "
            "leagues = '[\"nhl\"]' WHERE id = ?",
            (source_id,),
        )
    other = _group(80, "LIVE | NBA (Thur)")
    gap, _, _ = _scan([other], {80: [_stream(2, "nba: C vs D")]}, now=NOW + timedelta(days=1))
    assert gap.sources_rebound == 0

    taken = _group(81, "LIVE | NHL (Tue)", streams=30)
    no_games = _group(82, "LIVE | NHL (Wed)", streams=25)
    wrong_account = _group(83, "LIVE | NHL (Sat)", streams=24)
    older = _group(84, "LIVE | NHL (Thur)", streams=15)
    preferred = _group(85, "LIVE | NHL (Fri)", streams=15)
    with get_db() as conn:
        create_group(conn, name="Already taken", leagues=[], m3u_group_id=taken.id)
    foreign_stream = _stream(3, "nhl: E vs F")
    foreign_stream.m3u_account_id = 99
    now = NOW + timedelta(days=2)
    result, _, _ = _scan(
        [taken, no_games, wrong_account, older, preferred],
        {
            82: [_stream(2, "NHL News")],
            83: [foreign_stream],
            84: [_stream(4, "nhl: A vs C")],
            85: [_stream(5, "nhl: B vs D")],
        },
        now=now,
    )
    assert result.sources_rebound == 1 and result.sources_auto_added == 0
    current = _by_name(now)[preferred.name]
    assert (current.id, current.source_group_id) == (candidate.id, source_id)
    with get_db() as conn:
        source = conn.execute(
            "SELECT name, leagues, m3u_group_id, m3u_group_name, source_missing "
            "FROM event_epg_groups WHERE id = ?",
            (source_id,),
        ).fetchone()
    assert tuple(source) == ("My NHL", '["nhl"]', preferred.id, preferred.name, 0)


@pytest.mark.parametrize("managed, old_id_live", [(False, False), (True, True)])
def test_rotation_leaves_manual_sources_and_live_bindings_alone(db, managed, old_id_live):
    wed, thu = _group(71, "LIVE | NHL (Wed)"), _group(72, "LIVE | NHL (Thur)")
    with get_db() as conn:
        source_id = create_group(
            conn, name="My NHL", leagues=[], m3u_group_id=wed.id, m3u_group_name=wed.name
        )
        conn.execute("UPDATE event_epg_groups SET managed = ? WHERE id = ?", (managed, source_id))
    groups = [wed, thu] if old_id_live else [thu]
    result, _, _ = _scan(groups, {thu.id: [_stream(1, "nhl: A vs B")]})
    assert result.sources_rebound == 0
    with get_db() as conn:
        assert (
            conn.execute(
                "SELECT m3u_group_id FROM event_epg_groups WHERE id = ?", (source_id,)
            ).fetchone()[0]
            == wed.id
        )


def test_dismissing_rotating_group_on_one_account_does_not_block_another_accounts_rebind(db):
    def _acct_stream(stream_id: int, name: str, account_id: int):
        s = _stream(stream_id, name)
        s.m3u_account_id = account_id
        return s

    wed_a1, wed_a2 = _group(71, "LIVE | NHL (Wed)"), _group(72, "LIVE | NHL (Wed)")
    _scan(
        [wed_a1, wed_a2],
        {
            71: [_acct_stream(1, "nhl: A vs B", account_id=1)],
            72: [_acct_stream(2, "nhl: A vs B", account_id=2)],
        },
    )
    with get_db() as conn:
        cands = {c.m3u_group_id: c for c in get_candidates(conn, NOW, EVIDENCE_WINDOW_DAYS)}
        # Dismiss Account 2's copy; accept Account 1's copy as a managed source.
        set_candidate_status(conn, cands[72].id, "dismissed")
        visible = get_candidates(conn, NOW, EVIDENCE_WINDOW_DAYS, status="new")
        assert [c.m3u_group_id for c in visible] == [71]
        source_id = accept_candidate(conn, cands[71])

    # Account 1's candidate must not be hidden by Account 2's dismissal, and
    # when both rotate to Thursday, Account 1's managed source still rebinds.
    thu_a1, thu_a2 = _group(81, "LIVE | NHL (Thur)"), _group(82, "LIVE | NHL (Thur)")
    later = NOW + timedelta(days=1)
    result, _, _ = _scan(
        [thu_a1, thu_a2],
        {
            81: [_acct_stream(3, "nhl: C vs D", account_id=1)],
            82: [_acct_stream(4, "nhl: C vs D", account_id=2)],
        },
        now=later,
    )
    assert result.sources_rebound == 1
    with get_db() as conn:
        bound_id = conn.execute(
            "SELECT m3u_group_id FROM event_epg_groups WHERE id = ?", (source_id,)
        ).fetchone()[0]
        all_cands = get_candidates(conn, later, EVIDENCE_WINDOW_DAYS)
    assert bound_id == thu_a1.id
    # Account 2 said no to (Wed), not to (Thur): that day is its own suggestion.
    assert {(c.m3u_group_id, c.m3u_account_id, c.status) for c in all_cands} == {
        (thu_a1.id, 1, "accepted"),
        (wed_a2.id, 2, "dismissed"),
        (thu_a2.id, 2, "new"),
    }


@pytest.mark.parametrize("has_linked_candidate", [True, False])
@pytest.mark.parametrize("dismissed_account", [4, 0])
def test_rebind_rotating_sources_iterates_past_blocked_replacement_and_requires_account_match(
    db, has_linked_candidate, dismissed_account
):
    from teamarr.consumers.source_lifecycle.discovery import ScanSummary, rebind_rotating_sources

    with get_db() as conn:
        # Source 1 bound to account 4 on group 71; Source 2 unbound (account_id=None) on group 72
        s1 = create_group(
            conn,
            name="Acc4 NHL",
            leagues=[],
            m3u_group_id=71,
            m3u_group_name="LIVE | NHL (Wed)",
            m3u_account_id=4,
        )
        s2 = create_group(
            conn,
            name="Unbound NHL",
            leagues=[],
            m3u_group_id=72,
            m3u_group_name="LIVE | NHL (Wed)",
            m3u_account_id=None,
        )
        conn.execute("UPDATE event_epg_groups SET managed = 1 WHERE id IN (?, ?)", (s1, s2))
        conn.execute(
            "INSERT INTO source_candidates "
            "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
            "VALUES (72, 'LIVE | NHL (Wed)', 0, 'accepted', ?), "
            "       (90, 'LIVE | NHL (Fri)', ?, 'dismissed', NULL)",
            (s2, dismissed_account),
        )
        if has_linked_candidate:
            conn.execute(
                "INSERT INTO source_candidates "
                "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
                "VALUES (71, 'LIVE | NHL (Wed)', 4, 'accepted', ?)",
                (s1,),
            )

        # Group 90 has higher rank than Group 85, but is dismissed on account 4 or unscoped.
        # Group 85 is valid for account 4.
        # Unbound source s2 (account_id=None) should NOT rebind to account-4 evidence (group 86).
        evidence = [
            ScanEvidence(
                m3u_group_id=90,
                m3u_group_name="LIVE | NHL (Fri)",
                m3u_account_id=4,
                stream_count=50,
                game_matches=5,
            ),
            ScanEvidence(
                m3u_group_id=85,
                m3u_group_name="LIVE | NHL (Thu)",
                m3u_account_id=4,
                stream_count=20,
                game_matches=3,
            ),
            ScanEvidence(
                m3u_group_id=86,
                m3u_group_name="LIVE | NHL (Sat)",
                m3u_account_id=4,
                stream_count=10,
                game_matches=2,
            ),
        ]
        summary = ScanSummary()
        rebind_rotating_sources(
            conn, NOW, live_ids={85, 86, 90}, evidence=evidence, summary=summary
        )
        conn.commit()

        s1_row = conn.execute(
            "SELECT m3u_group_id, m3u_group_name, m3u_account_id "
            "FROM event_epg_groups WHERE id = ?",
            (s1,),
        ).fetchone()
        s2_row = conn.execute(
            "SELECT m3u_group_id, m3u_account_id FROM event_epg_groups WHERE id = ?",
            (s2,),
        ).fetchone()
        candidates = conn.execute(
            "SELECT m3u_group_id, m3u_account_id, status, source_group_id "
            "FROM source_candidates WHERE m3u_group_id IN (85, 90) ORDER BY m3u_group_id"
        ).fetchall()
    assert summary.sources_rebound == 1
    assert tuple(s1_row) == (85, "LIVE | NHL (Thu)", 4)
    assert tuple(s2_row) == (72, None)
    assert [tuple(row) for row in candidates] == [
        (85, 4, "accepted", s1),
        (90, dismissed_account, "dismissed", None),
    ]


def test_a_sport_toggle_covers_every_league_of_the_sport(db):
    _toggle(sports=["football"])
    _two_days(
        2, "USA | NFL Teams Backup", 0, {}, name_leagues=["nfl"], team=30, team_leagues={"nfl": 30}
    )
    _two_days(3, "Sports | NCAAF", 20, {"college-football": 20})
    _two_days(4, "LIVE | NHL (Direct)", 8, {"nhl": 8})
    assert _auto().sources_auto_added == 2
    src = _sources()
    assert set(src) == {"USA | NFL Teams Backup", "Sports | NCAAF"}
    assert (src["USA | NFL Teams Backup"][3], src["USA | NFL Teams Backup"][4]) == (1, 0)


def test_one_day_of_evidence_is_not_enough(db):
    from teamarr.utilities.tz import now_utc

    _toggle(leagues=["nhl"])
    with get_db() as conn:
        record_scan(
            conn,
            [
                ScanEvidence(
                    m3u_group_id=1,
                    m3u_group_name="LIVE | NHL (Direct)",
                    stream_count=66,
                    streams_read=66,
                    game_matches=8,
                    leagues={"nhl": 8},
                )
            ],
            now_utc(),
        )
    assert _auto().sources_auto_added == 0
    with get_db() as conn:
        record_scan(
            conn,
            [
                ScanEvidence(
                    m3u_group_id=1,
                    m3u_group_name="LIVE | NHL (Direct)",
                    stream_count=66,
                    streams_read=66,
                    game_matches=8,
                    leagues={"nhl": 8},
                )
            ],
            now_utc() + timedelta(days=1),
        )
    from teamarr.consumers.source_lifecycle.discovery import ScanSummary, auto_add_sources

    s = ScanSummary()
    with get_db() as conn:
        auto_add_sources(conn, now_utc() + timedelta(days=1), s)
    assert s.sources_auto_added == 1


def test_a_group_over_the_size_cap_is_suggested_but_never_added(api):
    _toggle(leagues=["nhl"])
    _two_days(1, "USA: ESPN PLUS", 100, {"nhl": 82, "nfl": 5}, streams=2215)
    assert _auto().sources_auto_added == 0
    row = api.get("/api/v1/source-discovery/candidates").json()["candidates"][0]
    assert row["auto_hold"] == "more than 1000 streams"
    api.put("/api/v1/settings/scheduler", json={"source_discovery_auto_max_streams": 5000})
    assert _auto().sources_auto_added == 1


def test_name_only_dismissed_and_replay_groups_are_never_added(db):
    from teamarr.utilities.tz import now_utc

    _toggle(sports=["basketball", "hockey", "football"])
    _two_days(1, "Sports | NBA Extra", 0, {}, name_leagues=["nba"])
    with get_db() as conn:
        for day in (1, 0):
            record_scan(
                conn,
                [
                    ScanEvidence(
                        m3u_group_id=2,
                        m3u_group_name="Replay | NBA",
                        name_leagues=["nba"],
                        replay=True,
                    )
                ],
                now_utc() - timedelta(days=day),
            )
    _two_days(3, "LIVE | NHL (Direct)", 8, {"nhl": 8})
    with get_db() as conn:
        set_candidate_status(conn, _by_name()["LIVE | NHL (Direct)"].id, "dismissed")
    assert _auto().sources_auto_added == 0 and _sources() == {}


def test_the_review_list_says_why_automatic_mode_holds_a_group(api):
    _toggle(leagues=["nhl"])
    _two_days(1, "UK: CUP GAMES", 14, {"uefa.nations": 14})
    _two_days(2, "LIVE | NHL (Direct)", 8, {"nhl": 8})
    rows = {
        r["m3u_group_name"]: r
        for r in api.get("/api/v1/source-discovery/candidates").json()["candidates"]
    }
    assert rows["UK: CUP GAMES"]["auto_hold"] == "its leagues are not set to automatic"
    assert rows["LIVE | NHL (Direct)"]["auto_hold"] is None


def test_the_subscription_api_round_trips_the_toggles(api):
    resp = api.put(
        "/api/v1/sports-subscription",
        json={"auto_source_leagues": ["NHL", "nhl", "eng.1"], "auto_source_sports": ["Football"]},
    )
    assert resp.status_code == 200, resp.text
    body = api.get("/api/v1/sports-subscription").json()
    assert (body["auto_source_leagues"], body["auto_source_sports"]) == (
        ["eng.1", "nhl"],
        ["football"],
    )
    # leaving them out of an update keeps them
    api.put("/api/v1/sports-subscription", json={"leagues": ["nba"]})
    assert api.get("/api/v1/sports-subscription").json()["auto_source_leagues"] == ["eng.1", "nhl"]


def test_an_auto_added_source_is_marked_in_the_sources_list(api):
    _toggle(leagues=["nhl"])
    _two_days(1, "LIVE | NHL (Direct)", 8, {"nhl": 8})
    _auto()
    listed = api.get("/api/v1/groups").json()["groups"]
    src = next(g for g in listed if g["name"] == "LIVE | NHL (Direct)")
    assert src["managed"] is True and src["auto_added_at"]
