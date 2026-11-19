"""A candidate is one account's streams in one group (#1226).

A source reads one M3U account's streams in its group, so a group two accounts
carry is two candidates: each is scanned, suggested, accepted and dismissed on
its own, and the upgrade gives a discovered source a sibling per other account
so no stream stops being read.
"""

import json
from types import SimpleNamespace

from teamarr.consumers.event_group_processor.stream_fetcher import StreamFetcher
from teamarr.consumers.source_lifecycle.discovery import accept_candidate
from teamarr.database import get_db, init_db
from teamarr.database.groups import EventEPGGroup, create_group, get_group, set_group_managed
from teamarr.database.source_candidates import get_candidates, set_candidate_status
from tests.test_source_account_scope import _fetcher, _row
from tests.test_source_discovery import NOW, _scan, db  # noqa: F401


def _shared(id_, name, per_account=(10, 10)):
    """A group the listing shows two accounts carrying (counts, no account ids)."""
    return SimpleNamespace(
        id=id_, name=name, m3u_accounts=[{"stream_count": n} for n in per_account]
    )


def _stream(id_, name, account):
    return SimpleNamespace(id=id_, name=name, tvg_id=None, is_stale=False, m3u_account_id=account)


def _candidates():
    with get_db() as conn:
        return {(c.m3u_group_name, c.m3u_account_id): c for c in get_candidates(conn, NOW, 7)}


GAMES_3 = ["nhl: A vs B", "nhl: C vs D", "nhl: E vs F"]


def _two_accounts(group_id=7):
    return {
        group_id: [_stream(i, n, 3) for i, n in enumerate(GAMES_3, 1)]
        + [_stream(10 + i, n, 9) for i, n in enumerate(GAMES_3[:2], 1)]
        + [_stream(20, "placeholder", 9)]
    }


# --- the scan ---------------------------------------------------------------


def test_a_group_two_accounts_carry_is_two_candidates_with_their_own_evidence(db):  # noqa: F811
    summary, m3u, _ = _scan([_shared(7, "USA | NHL")], _two_accounts())
    assert m3u.read == [7]  # one read, split by the streams' own accounts
    found = _candidates()
    a, b = found[("USA | NHL", 3)], found[("USA | NHL", 9)]
    assert (a.stream_count, a.best_game_matches) == (3, 3)
    assert (b.stream_count, b.best_game_matches) == (3, 2)
    assert a.id != b.id
    assert summary.groups_scanned == 2


def test_a_source_on_one_account_leaves_the_other_account_a_candidate(db):  # noqa: F811
    with get_db() as conn:
        create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7, m3u_account_id=3)
    summary, m3u, _ = _scan([_shared(7, "USA | NHL")], _two_accounts())
    assert m3u.read == [7]
    assert set(_candidates()) == {("USA | NHL", 9)}


def test_a_source_with_no_account_takes_the_whole_group(db):  # noqa: F811
    with get_db() as conn:
        create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7)
    summary, m3u, _ = _scan([_shared(7, "USA | NHL")], _two_accounts())
    assert m3u.read == [] and summary.skipped_sources == 1
    assert _candidates() == {}


def test_both_accounts_sourced_leaves_nothing_to_record(db):  # noqa: F811
    with get_db() as conn:
        create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7, m3u_account_id=3)
        create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7, m3u_account_id=9)
    _scan([_shared(7, "USA | NHL")], _two_accounts())
    assert _candidates() == {}


def test_dismissing_one_account_says_nothing_about_the_other(db):  # noqa: F811
    _scan([_shared(7, "USA | NHL")], _two_accounts())
    with get_db() as conn:
        set_candidate_status(conn, _candidates()[("USA | NHL", 9)].id, "dismissed")
    summary, _, _ = _scan([_shared(7, "USA | NHL")], _two_accounts())
    found = _candidates()
    assert found[("USA | NHL", 9)].status == "dismissed"
    assert found[("USA | NHL", 3)].status == "new"
    assert found[("USA | NHL", 3)].scans == 2 and found[("USA | NHL", 9)].scans == 1
    assert summary.skipped_dismissed == 1


def test_a_dismissed_account_stays_dismissed_under_a_new_group_id(db):  # noqa: F811
    _scan([_shared(7, "USA | NHL")], _two_accounts())
    with get_db() as conn:
        set_candidate_status(conn, _candidates()[("USA | NHL", 9)].id, "dismissed")
    _scan([_shared(70, "usa | nhl ")], _two_accounts(70))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m3u_account_id, status FROM source_candidates WHERE m3u_group_id = 70 "
            "ORDER BY m3u_account_id"
        ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(3, "new"), (9, "dismissed")]


def test_accepting_each_account_makes_two_sources_with_the_group_name(db):  # noqa: F811
    _scan([_shared(7, "USA | NHL")], _two_accounts())
    with get_db() as conn:
        ids = [
            accept_candidate(
                conn, _candidates()[("USA | NHL", account)], account_names={3: "East", 9: "West"}
            )
            for account in (3, 9)
        ]
        sources = [get_group(conn, i) for i in ids]
    assert [(s.name, s.m3u_group_id, s.m3u_account_id, s.m3u_account_name) for s in sources] == [
        ("USA | NHL", 7, 3, "East"),
        ("USA | NHL", 7, 9, "West"),
    ]


def test_streams_with_no_account_are_their_own_candidate(db):  # noqa: F811
    _scan([_shared(7, "Custom")], {7: [_stream(1, "nhl: A vs B", None)]})
    cand = _candidates()[("Custom", None)]
    assert cand.m3u_account_ids == [] and cand.best_game_matches == 1
    with get_db() as conn:
        source = get_group(conn, accept_candidate(conn, cand))
    assert source.m3u_account_id is None


# --- the upgrade (v105) -----------------------------------------------------

OLD_CANDIDATES = """
CREATE TABLE source_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    m3u_group_id INTEGER NOT NULL UNIQUE,
    m3u_group_name TEXT NOT NULL,
    m3u_account_ids TEXT NOT NULL DEFAULT '[]',
    stream_count INTEGER DEFAULT 0,
    name_leagues TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'accepted', 'dismissed')),
    source_group_id INTEGER,
    replay BOOLEAN DEFAULT 0,
    last_seen_at TIMESTAMP,
    last_matched_at TIMESTAMP
)
"""


def _old_candidate(conn, cid, group_id, name, accounts, status="new", source=None):
    conn.execute(
        "INSERT INTO source_candidates (id, m3u_group_id, m3u_group_name, m3u_account_ids, "
        "status, source_group_id, name_leagues) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, group_id, name, json.dumps(accounts), status, source, json.dumps(["nhl"])),
    )
    conn.execute(
        "INSERT INTO source_candidate_scans (candidate_id, scanned_at, streams_read, "
        "game_matches) VALUES (?, '2026-11-10 11:00:00', 6, 4)",
        (cid,),
    )


def _upgrade(seed):
    """A v104 database with the old candidate table, taken through init_db."""
    with get_db() as conn:
        conn.execute("DROP TABLE source_candidates")
        conn.execute(OLD_CANDIDATES)
        conn.execute("UPDATE settings SET schema_version = 104 WHERE id = 1")
        seed(conn)
        conn.commit()
    init_db()


def _rows():
    with get_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, m3u_group_id, m3u_account_id, status, source_group_id "
                "FROM source_candidates ORDER BY m3u_group_id, m3u_account_id"
            )
        ]


def _sources(group_id):
    with get_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, name, m3u_account_id, m3u_account_name, managed, enabled, "
                "team_streams_enabled, auto_added_at FROM event_epg_groups "
                "WHERE m3u_group_id = ? ORDER BY id",
                (group_id,),
            )
        ]


def test_upgrade_gives_a_discovered_source_a_sibling_per_other_account(db):  # noqa: F811
    def seed(conn):
        source = create_group(
            conn,
            name="USA | NHL",
            leagues=[],
            m3u_group_id=7,
            m3u_account_id=3,
            m3u_account_name="Provider A",
            team_streams_enabled=True,
        )
        set_group_managed(conn, source, True, auto_added_at="2026-11-01 11:07:00")
        # Another source tells the migration what account 9 is called.
        create_group(
            conn,
            name="Other",
            leagues=[],
            m3u_group_id=8,
            m3u_account_id=9,
            m3u_account_name="Provider B",
        )
        _old_candidate(conn, 5, 7, "USA | NHL", [3, 9], "accepted", source)

    _upgrade(seed)
    first, sibling = _sources(7)
    assert (first["m3u_account_id"], sibling["m3u_account_id"]) == (3, 9)
    assert sibling["name"] == "USA | NHL" and sibling["m3u_account_name"] == "Provider B"
    assert sibling["managed"] == 1 and sibling["enabled"] == 1
    assert sibling["team_streams_enabled"] == 1
    assert sibling["auto_added_at"] == first["auto_added_at"]
    assert _rows() == [
        {
            "id": 5,
            "m3u_group_id": 7,
            "m3u_account_id": 3,
            "status": "accepted",
            "source_group_id": first["id"],
        },
        {
            "id": 6,
            "m3u_group_id": 7,
            "m3u_account_id": 9,
            "status": "accepted",
            "source_group_id": sibling["id"],
        },
    ]
    with get_db() as conn:
        scans = conn.execute(
            "SELECT candidate_id, game_matches FROM source_candidate_scans"
        ).fetchall()
        version = conn.execute("SELECT schema_version FROM settings").fetchone()[0]
    assert [(s[0], s[1]) for s in scans] == [(5, 4)]  # history stays with the original
    assert version == 105


def test_upgrade_is_safe_to_run_again(db):  # noqa: F811
    def seed(conn):
        source = create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7, m3u_account_id=3)
        set_group_managed(conn, source, True)
        _old_candidate(conn, 5, 7, "USA | NHL", [3, 9], "accepted", source)

    _upgrade(seed)
    before = (_rows(), _sources(7))
    init_db()
    assert (_rows(), _sources(7)) == before


def test_upgrade_leaves_a_source_the_user_made_without_a_sibling(db):  # noqa: F811
    def seed(conn):
        # Automated by hand: its row lists only its own account.
        managed = create_group(conn, name="Mine", leagues=[], m3u_group_id=7, m3u_account_id=3)
        set_group_managed(conn, managed, True)
        _old_candidate(conn, 5, 7, "Mine", [3], "accepted", managed)
        # Accepted, then released from Automation: not managed any more.
        released = create_group(conn, name="Free", leagues=[], m3u_group_id=8, m3u_account_id=3)
        _old_candidate(conn, 6, 8, "Free", [3, 9], "accepted", released)

    _upgrade(seed)
    assert len(_sources(7)) == 1 and len(_sources(8)) == 1
    assert [(r["m3u_group_id"], r["m3u_account_id"]) for r in _rows()] == [(7, 3), (8, 3)]


def test_upgrade_does_not_double_a_half_that_already_has_a_source(db):  # noqa: F811
    def seed(conn):
        source = create_group(conn, name="USA | NHL", leagues=[], m3u_group_id=7, m3u_account_id=3)
        set_group_managed(conn, source, True)
        create_group(conn, name="NHL mirror", leagues=[], m3u_group_id=7, m3u_account_id=9)
        _old_candidate(conn, 5, 7, "USA | NHL", [3, 9], "accepted", source)

    _upgrade(seed)
    assert [s["name"] for s in _sources(7)] == ["USA | NHL", "NHL mirror"]
    assert [(r["m3u_account_id"], r["status"]) for r in _rows()] == [(3, "accepted")]


def test_upgrade_keeps_decisions_for_every_account(db):  # noqa: F811
    def seed(conn):
        _old_candidate(conn, 1, 7, "No thanks", [3, 9], "dismissed")
        _old_candidate(conn, 2, 8, "Approved, group gone", [3, 9], "accepted")
        _old_candidate(conn, 3, 9, "Undecided", [3, 9], "new")
        _old_candidate(conn, 4, 10, "No account", [], "new")

    _upgrade(seed)
    assert [(r["m3u_group_id"], r["m3u_account_id"], r["status"]) for r in _rows()] == [
        (7, 3, "dismissed"),
        (7, 9, "dismissed"),
        (8, 3, "accepted"),
        (8, 9, "accepted"),
        (9, 3, "new"),  # account 9 is recorded by the next scan, on its own evidence
        (10, 0, "new"),
    ]
    assert {r["id"] for r in _rows()} >= {1, 2, 3, 4}


# --- a stored account Dispatcharr no longer has (#628) -----------------------


def _source(account_id):
    return EventEPGGroup(id=1, name="Source", m3u_group_id=303, m3u_account_id=account_id)


def test_a_source_bound_to_a_vanished_account_reads_the_group():
    fetcher, _ = _fetcher([_row(1001, 101), _row(1002, 202)])
    streams = StreamFetcher._fetch_streams(fetcher, _source(555))
    assert sorted(s["id"] for s in streams) == [1001, 1002]


def test_a_live_account_with_no_streams_reads_nothing():
    fetcher, _ = _fetcher([_row(1001, 101)])
    assert StreamFetcher._fetch_streams(fetcher, _source(202)) == []


def test_an_unreadable_account_list_never_widens_the_read():
    fetcher, _ = _fetcher([_row(1001, 101)])
    fetcher._account_name_cache = {}
    assert StreamFetcher._fetch_streams(fetcher, _source(555)) == []
