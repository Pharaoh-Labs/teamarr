"""Source discovery: scan M3U groups that are not sources (#997)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.consumers.matching import StreamCategory
from teamarr.consumers.source_discovery import (
    TIER_GAMES,
    TIER_NAME_ONLY,
    SourceDiscovery,
    league_name_surfaces,
    leagues_named_by,
    sample_streams,
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
                results.append(SimpleNamespace(matched=True, stream_id=s["id"], league=league,
                                               category=StreamCategory.TEAM_VS_TEAM))
            elif league == "team":
                results.append(SimpleNamespace(matched=True, stream_id=s["id"], league="nba",
                                               category=StreamCategory.TEAM_ONLY))
            else:
                results.append(SimpleNamespace(matched=False, stream_id=s["id"], league=None,
                                               category=None))
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
    streams = {7: [_stream(1, "nhl: A vs B"), _stream(2, "nhl: C vs D"), _stream(3, "nba: E vs F"),
                   _stream(4, "ESPN News")]}
    summary, _, _ = _scan([_group(7, "USA | ESPN Plus")], streams)
    cand = _by_name()["USA | ESPN Plus"]
    assert (cand.best_game_matches, cand.leagues) == (3, {"nhl": 2, "nba": 1})
    assert cand.m3u_account_ids == [4]
    assert summary.groups_with_games == 1


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
        create_group(conn, name="By pattern", leagues=[], m3u_group_name_pattern=r"EPL \(MW\d+\)",
                     m3u_group_name_pattern_enabled=True)
        create_group(conn, name="Disabled", leagues=[], m3u_group_id=9, enabled=False)
        conn.commit()
    groups = [_group(7, "USA | NBA"), _group(8, "EPL (MW7)"), _group(9, "Old"), _group(10, "New")]
    summary, m3u, _ = _scan(groups, {})
    assert m3u.read == [10]
    assert summary.skipped_sources == 3


def test_empty_and_dismissed_groups_are_not_read(db):
    _scan([_group(7, "Replay | NBA")], {7: [_stream(1, "old")]})
    with get_db() as conn:
        set_candidate_status(conn, _by_name()["Replay | NBA"].id, "dismissed")
    summary, m3u, _ = _scan([_group(7, "Replay | NBA"), _group(8, "Empty", streams=0)], {})
    assert m3u.read == []
    assert (summary.skipped_dismissed, summary.skipped_empty) == (1, 1)
    assert _by_name()["Replay | NBA"].status == "dismissed"


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
    return ScanEvidence(m3u_group_id=gid, m3u_group_name=name, streams_read=10,
                        game_matches=games, leagues={"eng.1": games} if games else {})


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
        id=1, m3u_group_id=7, m3u_group_name="g", m3u_account_ids=[], stream_count=10,
        name_leagues=list(name_leagues), status="new", source_group_id=None, last_seen_at=None,
        last_matched_at=None, best_game_matches=games, team_only_matches=team_only,
    )


@pytest.mark.parametrize("games, named, tier", [
    (3, False, TIER_GAMES),       # content alone
    (2, False, None),             # not enough without a name
    (1, True, TIER_GAMES),        # the name lowers the bar
    (0, True, TIER_NAME_ONLY),    # worth showing, never worth importing
    (0, False, None),
])
def test_the_suggestion_rule(games, named, tier):
    assert suggestion_tier(_cand(games, ["nba"] if named else [])) == tier


def test_team_only_matches_never_qualify_a_group():
    assert suggestion_tier(_cand(games=0, team_only=40)) is None


def test_the_sample_is_an_even_spread_not_the_first_block():
    streams = [{"id": i} for i in range(1000)]
    picked = [s["id"] for s in sample_streams(streams, 50)]
    assert len(picked) == 50 and picked[0] == 0 and picked[-1] >= 980
    assert sample_streams(streams[:10], 50) == streams[:10]


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
        record_scan(conn, [
            ScanEvidence(m3u_group_id=1, m3u_group_name="USA: ESPN PLUS", streams_read=50,
                         game_matches=9, leagues={"nhl": 9}),
            ScanEvidence(m3u_group_id=2, m3u_group_name="Replay | NBA", streams_read=19,
                         name_leagues=["nba"]),
            ScanEvidence(m3u_group_id=3, m3u_group_name="UK | News", streams_read=50,
                         team_only_matches=5),
            ScanEvidence(m3u_group_id=4, m3u_group_name="LIVE | NBA (Preseason)", streams_read=14,
                         game_matches=2, leagues={"nba": 2}, name_leagues=["nba"]),
        ], now)


def test_the_review_list_holds_only_groups_worth_suggesting_strongest_first(api):
    _seed()
    body = api.get("/api/v1/source-discovery/candidates").json()
    assert [(c["m3u_group_name"], c["tier"]) for c in body["candidates"]] == [
        ("USA: ESPN PLUS", "games"),
        ("LIVE | NBA (Preseason)", "games"),
        ("Replay | NBA", "name_only"),
    ]
    assert body["window_days"] == 7 and body["scan"]["running"] is False


def test_a_dismissed_candidate_leaves_the_list_and_can_be_restored(api):
    _seed()
    cid = api.get("/api/v1/source-discovery/candidates").json()["candidates"][2]["id"]
    assert api.post(f"/api/v1/source-discovery/candidates/{cid}/dismiss").status_code == 200
    names = lambda **p: [  # noqa: E731
        c["m3u_group_name"]
        for c in api.get("/api/v1/source-discovery/candidates", params=p).json()["candidates"]
    ]
    assert "Replay | NBA" not in names()
    assert "Replay | NBA" in names(include_dismissed=True)
    api.post(f"/api/v1/source-discovery/candidates/{cid}/restore")
    assert "Replay | NBA" in names()
    assert api.post("/api/v1/source-discovery/candidates/9999/dismiss").status_code == 404


def test_the_schedule_is_a_setting_and_a_bad_cron_is_refused(api):
    got = api.get("/api/v1/settings/scheduler").json()
    assert (got["source_discovery_mode"], got["source_discovery_cron"]) == ("off", "0 11 * * *")
    ok = api.put("/api/v1/settings/scheduler",
                 json={"source_discovery_mode": "suggest", "source_discovery_cron": "30 9 * * *"})
    assert ok.status_code == 200
    assert ok.json()["source_discovery_mode"] == "suggest"
    assert ok.json()["source_discovery_cron"] == "30 9 * * *"
    bad = api.put("/api/v1/settings/scheduler", json={"source_discovery_cron": "not a cron"})
    assert bad.status_code == 400
    assert api.put("/api/v1/settings/scheduler",
                   json={"source_discovery_mode": "sometimes"}).status_code == 422


def test_a_scan_is_skipped_without_dispatcharr_and_only_one_runs_at_a_time(db, monkeypatch):
    from teamarr.consumers import source_discovery as sd

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
    cid = api.get("/api/v1/source-discovery/candidates").json()["candidates"][0]["id"]
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
    from teamarr.consumers.source_discovery import ScanSummary, maintain_managed_sources
    from teamarr.utilities.tz import now_utc

    summary = ScanSummary()
    with get_db() as conn:
        maintain_managed_sources(conn, now_utc(), set(live), evidence or {}, summary)
    return summary


def test_accepting_a_candidate_creates_a_managed_source(api):
    cid, source_id = _accept_first(api)
    source = _source(source_id)
    assert (source.name, source.m3u_group_id, source.managed, source.enabled) == (
        "USA: ESPN PLUS", 1, True, True)
    listed = api.get("/api/v1/groups").json()["groups"]
    assert next(g for g in listed if g["id"] == source_id)["managed"] is True
    names = [c["m3u_group_name"]
             for c in api.get("/api/v1/source-discovery/candidates").json()["candidates"]]
    assert "USA: ESPN PLUS" not in names
    assert api.post(f"/api/v1/source-discovery/candidates/{cid}/accept").status_code == 409


def test_a_hand_edit_makes_a_managed_source_the_users_own(api):
    _, source_id = _accept_first(api)
    assert api.put(f"/api/v1/groups/{source_id}",
                   json={"subscription_leagues": ["nhl"]}).status_code == 200
    assert _source(source_id).managed is False


def test_disabling_by_hand_also_claims_it_so_discovery_never_turns_it_back_on(api):
    _, source_id = _accept_first(api)
    assert api.post(f"/api/v1/groups/{source_id}/disable").status_code == 200
    summary = _maintain(evidence={1: ScanEvidence(1, "USA: ESPN PLUS", game_matches=9)})
    source = _source(source_id)
    assert (source.managed, source.enabled, summary.sources_reenabled) == (False, False, 0)


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
    _maintain(live=())                     # idle -> disabled
    assert _maintain(live=()).sources_removed == 1   # created 15 days ago, group gone
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
    _maintain()            # disabled
    _maintain()            # still listed: last seen is now
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
