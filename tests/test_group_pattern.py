"""Group-name pattern binding (#450, epic bpqb).

Covers the resolver (regex over live M3U-provided group names), the
stream-fetch integration (union across resolved groups, account scoping),
stale detection for pattern-bound sources, and the CRUD roundtrip.
"""

import contextlib
import sqlite3
from types import SimpleNamespace

from teamarr.consumers.event_group_processor.stream_fetcher import StreamFetcher
from teamarr.consumers.reconciliation import detect_stale_groups
from teamarr.database.groups import EventEPGGroup, create_group, get_group, update_group
from teamarr.services.group_pattern import (
    compile_group_pattern,
    find_rebind_suggestions,
    resolve_group_name_pattern,
    suggest_pattern,
)
from tests.helpers import SCHEMA_PATH


def _grp(gid, name, m3u=True):
    return SimpleNamespace(id=gid, name=name, m3u_accounts=(1,) if m3u else ())


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TestResolver:
    LIVE = [
        _grp(1, "EPL (MW1)"),
        _grp(2, "EPL (MW2)"),
        _grp(3, "USA | MLB"),
        _grp(4, "epl classics", m3u=False),  # not M3U-provided
    ]

    def test_matches_by_regex(self):
        got = resolve_group_name_pattern(self.LIVE, r"EPL \(MW\d+\)")
        assert [g.id for g in got] == [1, 2]

    def test_case_insensitive_search(self):
        got = resolve_group_name_pattern(self.LIVE, r"usa \| mlb")
        assert [g.id for g in got] == [3]

    def test_non_m3u_groups_excluded(self):
        # "epl classics" matches the regex but has no M3U account relation.
        got = resolve_group_name_pattern(self.LIVE, r"epl")
        assert [g.id for g in got] == [1, 2]

    def test_missing_m3u_accounts_field_fails_closed(self):
        bare = [SimpleNamespace(id=9, name="EPL (MW3)")]
        assert resolve_group_name_pattern(bare, r"EPL") == []

    def test_invalid_pattern_returns_empty(self):
        assert resolve_group_name_pattern(self.LIVE, r"EPL (") == []
        assert compile_group_pattern(r"EPL (") is None

    def test_empty_pattern_returns_empty(self):
        assert resolve_group_name_pattern(self.LIVE, None) == []
        assert resolve_group_name_pattern(self.LIVE, "   ") == []


# ---------------------------------------------------------------------------
# Stream-fetch integration
# ---------------------------------------------------------------------------


def _stream(sid, name, account=7):
    return SimpleNamespace(
        id=sid,
        name=name,
        tvg_id=None,
        tvg_name=None,
        url=None,
        channel_group=None,
        channel_group_id=None,
        m3u_account_id=account,
        is_stale=False,
    )


class _FakeM3U:
    def __init__(self, groups, streams_by_group):
        self._groups = groups
        self._streams_by_group = streams_by_group
        self.stream_calls: list[tuple] = []

    def list_groups(self):
        return self._groups

    def list_accounts(self, include_custom=False):
        return [SimpleNamespace(id=7, name="Acct")]

    def list_streams(self, group_name=None, group_id=None, account_id=None, limit=None):
        self.stream_calls.append((group_name, account_id))
        return self._streams_by_group.get(group_name, [])


class _Fetcher(StreamFetcher):
    def __init__(self, m3u):
        self._dispatcharr_client = SimpleNamespace(m3u=m3u)
        self._db_factory = None
        self._service = None


def _pattern_group(pattern, account_id=7):
    return EventEPGGroup(
        id=1,
        name="EPL",
        m3u_group_id=999,  # dead pinned id — pattern must win
        m3u_account_id=account_id,
        m3u_group_name_pattern=pattern,
        m3u_group_name_pattern_enabled=True,
    )


class TestPatternFetch:
    def test_unions_streams_across_resolved_groups(self):
        m3u = _FakeM3U(
            groups=[_grp(1, "EPL (MW1)"), _grp(2, "EPL (MW2)"), _grp(3, "USA | MLB")],
            streams_by_group={
                "EPL (MW1)": [_stream(11, "Arsenal vs Spurs")],
                "EPL (MW2)": [_stream(12, "Chelsea vs Wolves"), _stream(11, "Arsenal vs Spurs")],
            },
        )
        fetcher = _Fetcher(m3u)
        streams = fetcher._fetch_streams(_pattern_group(r"EPL \(MW\d+\)"))
        assert sorted(s["id"] for s in streams) == [11, 12]  # deduped union

    def test_account_id_scopes_stream_fetch(self):
        m3u = _FakeM3U(
            groups=[_grp(1, "EPL (MW1)")],
            streams_by_group={"EPL (MW1)": [_stream(11, "Arsenal vs Spurs")]},
        )
        fetcher = _Fetcher(m3u)
        fetcher._fetch_streams(_pattern_group(r"EPL", account_id=7))
        assert m3u.stream_calls == [("EPL (MW1)", 7)]

    def test_no_match_returns_empty_not_all_streams(self):
        m3u = _FakeM3U(groups=[_grp(3, "USA | MLB")], streams_by_group={})
        fetcher = _Fetcher(m3u)
        assert fetcher._fetch_streams(_pattern_group(r"EPL")) == []
        assert m3u.stream_calls == []  # never fell through to unfiltered fetch

    def test_disabled_pattern_uses_pinned_id(self):
        m3u = _FakeM3U(groups=[_grp(1, "EPL (MW1)")], streams_by_group={})
        calls = []
        m3u.list_streams = lambda **kw: calls.append(kw) or []
        fetcher = _Fetcher(m3u)
        group = _pattern_group(r"EPL")
        group.m3u_group_name_pattern_enabled = False
        fetcher._fetch_streams(group)
        assert calls == [{"group_id": 999}]


# ---------------------------------------------------------------------------
# Stale detection (pattern-bound sources)
# ---------------------------------------------------------------------------


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _factory(conn):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


def _add_pattern_group(conn, name, pattern, m3u_group_id=999):
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, m3u_group_id, m3u_group_name_pattern, "
        " m3u_group_name_pattern_enabled, enabled) "
        "VALUES (?, '[]', ?, ?, 1, 1)",
        (name, m3u_group_id, pattern),
    )
    conn.commit()


def _patch_dispatcharr(monkeypatch, groups):
    import teamarr.consumers.reconciliation as reconciliation

    fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=lambda: groups))
    monkeypatch.setattr(reconciliation, "get_dispatcharr_connection", lambda db_factory=None: fake)


class TestPatternStaleDetection:
    def test_pattern_match_marks_seen_despite_dead_pinned_id(self, monkeypatch):
        conn = _db()
        _add_pattern_group(conn, "EPL", r"EPL \(MW\d+\)", m3u_group_id=999)
        _patch_dispatcharr(monkeypatch, [_grp(2, "EPL (MW2)")])  # id 999 long gone

        assert detect_stale_groups(_factory(conn)) == []
        row = conn.execute(
            "SELECT source_missing, source_last_seen FROM event_epg_groups WHERE name='EPL'"
        ).fetchone()
        assert row["source_missing"] == 0
        assert row["source_last_seen"] is not None

    def test_pattern_without_match_marks_missing(self, monkeypatch):
        conn = _db()
        _add_pattern_group(conn, "EPL", r"EPL \(MW\d+\)")
        _patch_dispatcharr(monkeypatch, [_grp(3, "USA | MLB")])

        stale = detect_stale_groups(_factory(conn))
        assert {g["name"] for g in stale} == {"EPL"}

    def test_pattern_group_without_pinned_id_is_evaluated(self, monkeypatch):
        conn = _db()
        _add_pattern_group(conn, "EPL", r"EPL", m3u_group_id=None)
        _patch_dispatcharr(monkeypatch, [_grp(2, "EPL (MW2)")])

        assert detect_stale_groups(_factory(conn)) == []


# ---------------------------------------------------------------------------
# CRUD roundtrip
# ---------------------------------------------------------------------------


class TestCrudRoundtrip:
    def test_create_and_read_pattern_fields(self):
        conn = _db()
        gid = create_group(
            conn,
            name="EPL",
            leagues=["eng.1"],
            m3u_group_name_pattern=r"EPL \(MW\d+\)",
            m3u_group_name_pattern_enabled=True,
        )
        group = get_group(conn, gid)
        assert group.m3u_group_name_pattern == r"EPL \(MW\d+\)"
        assert group.m3u_group_name_pattern_enabled is True

    def test_update_and_clear_pattern(self):
        conn = _db()
        gid = create_group(conn, name="EPL", leagues=["eng.1"])
        update_group(
            conn, gid, m3u_group_name_pattern=r"EPL", m3u_group_name_pattern_enabled=True
        )
        group = get_group(conn, gid)
        assert group.m3u_group_name_pattern == "EPL"
        assert group.m3u_group_name_pattern_enabled is True

        update_group(
            conn, gid, clear_m3u_group_name_pattern=True, m3u_group_name_pattern_enabled=False
        )
        group = get_group(conn, gid)
        assert group.m3u_group_name_pattern is None
        assert group.m3u_group_name_pattern_enabled is False


# ---------------------------------------------------------------------------
# Pattern suggestion generator (bpqb.5)
# ---------------------------------------------------------------------------


def _matches(pattern: str, name: str) -> bool:
    rx = compile_group_pattern(pattern)
    return rx is not None and rx.search(name) is not None


class TestSuggestPattern:
    def test_numeric_token_becomes_digit_class(self):
        pattern = suggest_pattern("EPL (MW1)", "EPL (MW2)")
        assert pattern is not None
        assert r"\d+" in pattern
        for name in ("EPL (MW1)", "EPL (MW2)", "EPL (MW14)"):
            assert _matches(pattern, name)
        assert not _matches(pattern, "EPL classics")
        assert not _matches(pattern, "LIVE EPL (MW1) HD")  # anchored

    def test_non_numeric_token_becomes_wildcard(self):
        pattern = suggest_pattern("NFL - Week One", "NFL - Week Two")
        assert pattern is not None
        assert _matches(pattern, "NFL - Week Fifteen")

    def test_containment_rename_uses_optional_wildcard(self):
        pattern = suggest_pattern("LIVE EPL", "LIVE EPL (MW2)")
        assert pattern is not None
        assert _matches(pattern, "LIVE EPL")
        assert _matches(pattern, "LIVE EPL (MW9)")

    def test_regex_metachars_are_escaped(self):
        pattern = suggest_pattern("USA | MLB ⚾ (1)", "USA | MLB ⚾ (2)")
        assert pattern is not None
        assert _matches(pattern, "USA | MLB ⚾ (7)")
        assert not _matches(pattern, "USA x MLB ⚾ (7)")  # '|' must not be an alternation

    def test_unrelated_names_yield_nothing(self):
        assert suggest_pattern("EPL (MW1)", "USA | MLB") is None

    def test_too_little_stable_text_yields_nothing(self):
        # Common prefix "EPL" is only 3 chars — "^EPL.*$"-style patterns are
        # rejected outright when below the literal minimum.
        assert suggest_pattern("EPL", "EPL2") is None

    def test_identical_or_empty_names_yield_nothing(self):
        assert suggest_pattern("EPL (MW1)", "EPL (MW1)") is None
        assert suggest_pattern("", "EPL (MW1)") is None
        assert suggest_pattern("EPL (MW1)", "") is None


# ---------------------------------------------------------------------------
# Stale-source rebind suggestions (bpqb.4)
# ---------------------------------------------------------------------------


def _stale_row(gid=5, name="EPL", old="EPL (MW1)"):
    return {"id": gid, "name": name, "display_name": None, "m3u_group_name": old}


class TestFindRebindSuggestions:
    def test_suggests_closest_unbound_m3u_group(self):
        live = [_grp(42, "EPL (MW2)"), _grp(43, "USA | MLB")]
        got = find_rebind_suggestions([_stale_row()], live, bound_group_ids=set())
        assert len(got) == 1
        s = got[0]
        assert s["group_id"] == 5
        assert s["candidate_group_id"] == 42
        assert s["candidate_group_name"] == "EPL (MW2)"
        assert s["similarity"] >= 0.6
        assert s["suggested_pattern"] is not None

    def test_bound_groups_are_not_candidates(self):
        live = [_grp(42, "EPL (MW2)")]
        got = find_rebind_suggestions([_stale_row()], live, bound_group_ids={42})
        assert got == []

    def test_non_m3u_groups_are_not_candidates(self):
        live = [_grp(42, "EPL (MW2)", m3u=False)]
        got = find_rebind_suggestions([_stale_row()], live, bound_group_ids=set())
        assert got == []

    def test_dissimilar_names_are_not_suggested(self):
        live = [_grp(43, "USA | MLB")]
        got = find_rebind_suggestions([_stale_row()], live, bound_group_ids=set())
        assert got == []

    def test_picks_best_of_several_candidates(self):
        live = [_grp(41, "EPL 4K (MW2)"), _grp(42, "EPL (MW2)")]
        got = find_rebind_suggestions([_stale_row()], live, bound_group_ids=set())
        assert [s["candidate_group_id"] for s in got] == [42]

    def test_stale_source_without_group_name_is_skipped(self):
        live = [_grp(42, "EPL (MW2)")]
        got = find_rebind_suggestions(
            [_stale_row(old=None)], live, bound_group_ids=set()
        )
        assert got == []

    def test_candidates_scoped_to_source_account(self):
        # A near-identical group exists on ANOTHER account (id 99) — a rename
        # happens within one playlist, so only the source's own account may
        # match, whichever side of the fence the account map puts each group.
        row = {**_stale_row(), "m3u_account_id": 7}
        live = [_grp(42, "EPL (MW2)"), _grp(99, "EPL (MW3)")]
        got = find_rebind_suggestions(
            [row], live, bound_group_ids=set(), account_group_ids={7: {42}}
        )
        assert [s["candidate_group_id"] for s in got] == [42]

        got = find_rebind_suggestions(
            [row], live, bound_group_ids=set(), account_group_ids={7: {99}}
        )
        assert [s["candidate_group_id"] for s in got] == [99]

    def test_account_bound_source_without_attribution_gets_no_suggestion(self):
        # Account detail fetch failed → never risk a cross-account suggestion.
        row = {**_stale_row(), "m3u_account_id": 7}
        live = [_grp(42, "EPL (MW2)")]
        got = find_rebind_suggestions(
            [row], live, bound_group_ids=set(), account_group_ids={}
        )
        assert got == []

    def test_source_without_account_scans_all_m3u_groups(self):
        row = {**_stale_row(), "m3u_account_id": None}
        live = [_grp(42, "EPL (MW2)")]
        got = find_rebind_suggestions([row], live, bound_group_ids=set())
        assert [s["candidate_group_id"] for s in got] == [42]


# ---------------------------------------------------------------------------
# Cleanup safety (bpqb.8)
#
# A pattern that stops matching (provider rename escaping the regex, M3U
# outage) must NEVER cascade into channel deletion. The guarantee lives in
# _process_group_internal's short-circuits: an empty fetch — and an
# all-filtered / zero-match run — returns before cleanup_deleted_streams or
# any lifecycle call, so existing channels are retained untouched.
# ---------------------------------------------------------------------------


def _tripwire(name):
    def _fail(*args, **kwargs):
        raise AssertionError(f"{name} must not be called on this path")

    return _fail


def _seeded_group_db():
    """Schema DB with the template requirement satisfied and one real group."""
    conn = _db()
    cur = conn.execute("INSERT INTO templates (name, template_type) VALUES ('T', 'event')")
    conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (cur.lastrowid,))
    gid = create_group(
        conn,
        name="EPL",
        leagues=["eng.1"],
        m3u_group_name_pattern=r"EPL \(MW\d+\)",
        m3u_group_name_pattern_enabled=True,
    )
    conn.commit()
    return conn, get_group(conn, gid)


class TestCleanupSafety:
    def _processor(self, conn):
        from unittest.mock import MagicMock

        from teamarr.consumers.event_group_processor import EventGroupProcessor

        # Inject a stub service: the default one loads league mappings from the
        # global DB path, which doesn't exist in CI (and none of these paths
        # reach the provider layer anyway).
        return EventGroupProcessor(db_factory=_factory(conn), service=MagicMock())

    def test_empty_fetch_short_circuits_before_any_cleanup(self, monkeypatch):
        from datetime import date

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        monkeypatch.setattr(proc, "_fetch_streams", lambda g: [])
        for name in (
            "_filter_streams",
            "_match_streams",
            "_process_channels",
            "_get_lifecycle_service",
        ):
            monkeypatch.setattr(proc, name, _tripwire(name))

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == ["No streams found for group"]
        assert result.channels_deleted == 0

    def test_all_filtered_short_circuits_before_matching(self, monkeypatch):
        from datetime import date

        from teamarr.services.stream_filter import FilterResult

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        monkeypatch.setattr(
            proc, "_fetch_streams", lambda g: [{"id": 11, "name": "Arsenal vs Spurs"}]
        )
        monkeypatch.setattr(
            proc,
            "_filter_streams",
            lambda streams, g: ([], FilterResult(total_input=1, filtered_exclude=1)),
        )
        for name in ("_match_streams", "_process_channels", "_get_lifecycle_service"):
            monkeypatch.setattr(proc, name, _tripwire(name))

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == ["All streams filtered out by regex patterns"]
        assert result.channels_deleted == 0

    def test_zero_matches_never_reaches_lifecycle(self, monkeypatch):
        from datetime import date

        from teamarr.consumers.matching.matcher import BatchMatchResult
        from teamarr.services.stream_filter import FilterResult

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        streams = [{"id": 11, "name": "Arsenal vs Spurs"}]
        monkeypatch.setattr(proc, "_fetch_streams", lambda g: list(streams))
        monkeypatch.setattr(
            proc,
            "_filter_streams",
            lambda s, g: (list(streams), FilterResult(total_input=1, passed_count=1)),
        )
        monkeypatch.setattr(proc, "_match_streams", lambda *a, **k: BatchMatchResult())
        monkeypatch.setattr(proc, "_process_channels", _tripwire("_process_channels"))
        monkeypatch.setattr(proc, "_get_lifecycle_service", _tripwire("_get_lifecycle_service"))

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == []
        assert result.channels_deleted == 0
        assert result.streams_matched == 0


# ---------------------------------------------------------------------------
# API layer (bpqb.6)
# ---------------------------------------------------------------------------


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from teamarr.api.app import app  # noqa: E402
from teamarr.database import init_db  # noqa: E402

client = TestClient(app)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


class TestGroupsApi:
    def test_pattern_fields_round_trip(self, isolated_db):
        resp = client.post(
            "/api/v1/groups",
            json={
                "name": "EPL",
                "leagues": ["eng.1"],
                "m3u_group_name_pattern": r"EPL \(MW\d+\)",
                "m3u_group_name_pattern_enabled": True,
            },
        )
        assert resp.status_code == 201, resp.text
        gid = resp.json()["id"]

        got = client.get(f"/api/v1/groups/{gid}").json()
        assert got["m3u_group_name_pattern"] == r"EPL \(MW\d+\)"
        assert got["m3u_group_name_pattern_enabled"] is True

    def test_update_and_clear_pattern_fields(self, isolated_db):
        gid = client.post(
            "/api/v1/groups", json={"name": "EPL", "leagues": ["eng.1"]}
        ).json()["id"]

        resp = client.put(
            f"/api/v1/groups/{gid}",
            json={"m3u_group_name_pattern": "EPL", "m3u_group_name_pattern_enabled": True},
        )
        assert resp.status_code == 200, resp.text
        got = client.get(f"/api/v1/groups/{gid}").json()
        assert got["m3u_group_name_pattern"] == "EPL"
        assert got["m3u_group_name_pattern_enabled"] is True

        resp = client.put(
            f"/api/v1/groups/{gid}",
            json={
                "clear_m3u_group_name_pattern": True,
                "m3u_group_name_pattern_enabled": False,
            },
        )
        assert resp.status_code == 200, resp.text
        got = client.get(f"/api/v1/groups/{gid}").json()
        assert got["m3u_group_name_pattern"] is None
        assert got["m3u_group_name_pattern_enabled"] is False


class TestPatternPreviewApi:
    def _patch_dispatcharr(self, monkeypatch, groups):
        import teamarr.api.routes.groups as groups_routes

        fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=lambda: groups))
        monkeypatch.setattr(
            groups_routes, "get_dispatcharr_connection", lambda db_factory=None: fake
        )

    def test_preview_returns_matches(self, isolated_db, monkeypatch):
        self._patch_dispatcharr(
            monkeypatch, [_grp(1, "EPL (MW1)"), _grp(2, "EPL (MW2)"), _grp(3, "USA | MLB")]
        )
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview",
            json={"pattern": r"EPL \(MW\d+\)"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["valid"] is True
        assert body["total"] == 2
        assert [m["name"] for m in body["matches"]] == ["EPL (MW1)", "EPL (MW2)"]

    def test_preview_invalid_regex_is_soft_error(self, isolated_db, monkeypatch):
        self._patch_dispatcharr(monkeypatch, [_grp(1, "EPL (MW1)")])
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview",
            json={"pattern": "EPL ("},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["total"] == 0

    def test_preview_unconfigured_dispatcharr_is_400(self, isolated_db, monkeypatch):
        import teamarr.api.routes.groups as groups_routes

        monkeypatch.setattr(
            groups_routes, "get_dispatcharr_connection", lambda db_factory=None: None
        )
        resp = client.post(
            "/api/v1/groups/dispatcharr/group-pattern-preview", json={"pattern": "EPL"}
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rebind flywheel API (bpqb.4/.5)
# ---------------------------------------------------------------------------


def _patch_routes_dispatcharr(monkeypatch, groups, account_groups=None):
    import teamarr.api.routes.groups as groups_routes

    fake = SimpleNamespace(
        m3u=SimpleNamespace(
            list_groups=lambda: groups,
            get_account_group_counts=lambda aid: dict.fromkeys(account_groups or (), 1),
        )
    )
    monkeypatch.setattr(groups_routes, "get_dispatcharr_connection", lambda db_factory=None: fake)


def _create_stale_group(old_name="EPL (MW1)", account_id=None, **extra):
    from teamarr.database import get_db

    gid = client.post(
        "/api/v1/groups", json={"name": "EPL", "leagues": ["eng.1"], **extra}
    ).json()["id"]
    with get_db() as conn:
        conn.execute(
            "UPDATE event_epg_groups "
            "SET source_missing = 1, m3u_group_name = ?, m3u_group_id = 999, "
            "    m3u_account_id = ? WHERE id = ?",
            (old_name, account_id, gid),
        )
        conn.commit()
    return gid


class TestRebindApi:
    def test_suggestions_surface_near_match(self, isolated_db, monkeypatch):
        gid = _create_stale_group(account_id=7)
        _patch_routes_dispatcharr(
            monkeypatch,
            [_grp(42, "EPL (MW2)"), _grp(43, "USA | MLB")],
            account_groups={42, 43},
        )

        got = client.get("/api/v1/groups/stale/suggestions").json()
        assert len(got) == 1
        assert got[0]["group_id"] == gid
        assert got[0]["candidate_group_id"] == 42
        assert got[0]["suggested_pattern"] is not None

    def test_suggestions_exclude_other_accounts_groups(self, isolated_db, monkeypatch):
        _create_stale_group(account_id=7)
        # The near-match group exists but belongs to a DIFFERENT account.
        _patch_routes_dispatcharr(
            monkeypatch, [_grp(42, "EPL (MW2)")], account_groups={43}
        )
        assert client.get("/api/v1/groups/stale/suggestions").json() == []

    def test_suggestions_soft_empty_without_dispatcharr(self, isolated_db, monkeypatch):
        import teamarr.api.routes.groups as groups_routes

        _create_stale_group()
        monkeypatch.setattr(
            groups_routes, "get_dispatcharr_connection", lambda db_factory=None: None
        )
        resp = client.get("/api/v1/groups/stale/suggestions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_rebind_pins_group_and_clears_stale(self, isolated_db):
        # Pattern-bound source gone stale: a plain re-bind must also disable
        # the dead pattern, or stream fetch would keep using it over the pin.
        gid = _create_stale_group(
            m3u_group_name_pattern=r"DEAD \(\d+\)", m3u_group_name_pattern_enabled=True
        )
        resp = client.post(
            f"/api/v1/groups/{gid}/rebind",
            json={"m3u_group_id": 42, "m3u_group_name": "EPL (MW2)"},
        )
        assert resp.status_code == 200, resp.text

        got = client.get(f"/api/v1/groups/{gid}").json()
        assert got["m3u_group_id"] == 42
        assert got["m3u_group_name"] == "EPL (MW2)"
        assert got["m3u_group_name_pattern_enabled"] is False
        assert client.get("/api/v1/groups/stale").json() == []

    def test_rebind_with_pattern_enables_it(self, isolated_db):
        gid = _create_stale_group()
        resp = client.post(
            f"/api/v1/groups/{gid}/rebind",
            json={
                "m3u_group_id": 42,
                "m3u_group_name": "EPL (MW2)",
                "pattern": r"^EPL \(MW\d+\)$",
            },
        )
        assert resp.status_code == 200, resp.text
        got = client.get(f"/api/v1/groups/{gid}").json()
        assert got["m3u_group_id"] == 42
        assert got["m3u_group_name_pattern"] == r"^EPL \(MW\d+\)$"
        assert got["m3u_group_name_pattern_enabled"] is True
        assert client.get("/api/v1/groups/stale").json() == []

    def test_rebind_rejects_invalid_pattern(self, isolated_db):
        gid = _create_stale_group()
        resp = client.post(
            f"/api/v1/groups/{gid}/rebind",
            json={"m3u_group_id": 42, "m3u_group_name": "EPL (MW2)", "pattern": "EPL ("},
        )
        assert resp.status_code == 400

    def test_rebind_unknown_group_is_404(self, isolated_db):
        resp = client.post(
            "/api/v1/groups/999999/rebind",
            json={"m3u_group_id": 42, "m3u_group_name": "EPL (MW2)"},
        )
        assert resp.status_code == 404
