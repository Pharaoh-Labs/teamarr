"""Stale source-group detection (lylt.1).

A group is stale when its Dispatcharr M3U source channel-group no longer
exists. Off-season (group still exists, zero streams) must NOT be flagged, and
a Dispatcharr blip (empty/failed group list) must flag nothing.
"""

import contextlib
import sqlite3
from types import SimpleNamespace

import pytest

from teamarr.consumers.source_lifecycle import detect_stale_groups
from tests.helpers import SCHEMA_PATH

SCHEMA = SCHEMA_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _factory(conn: sqlite3.Connection):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


def _add_group(
    conn,
    name,
    m3u_group_id,
    *,
    enabled=1,
    is_channel_source=0,
    m3u_group_name=None,
    m3u_account_id=None,
):
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, m3u_group_id, m3u_group_name, enabled, is_channel_source, m3u_account_id) "
        "VALUES (?, '[]', ?, ?, ?, ?, ?)",
        (name, m3u_group_id, m3u_group_name, enabled, is_channel_source, m3u_account_id),
    )
    conn.commit()


def _patch_dispatcharr(monkeypatch, groups, *, get_account_group_counts=None):
    """Fake get_dispatcharr_connection -> .m3u.list_groups().

    `groups` items may be ints (auto-named) or (id, name) tuples.
    """
    import teamarr.consumers.source_lifecycle.missing as reconciliation

    def mk(item):
        if isinstance(item, tuple):
            return SimpleNamespace(
                id=item[0], name=item[1], m3u_accounts=item[2] if len(item) > 2 else []
            )
        return SimpleNamespace(id=item, name=f"live-{item}")

    fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=lambda: [mk(i) for i in groups]))
    if get_account_group_counts is not None:
        fake.m3u.get_account_group_counts = get_account_group_counts
    monkeypatch.setattr(reconciliation, "get_dispatcharr_connection", lambda db_factory=None: fake)


def test_missing_source_is_flagged(monkeypatch):
    conn = _db()
    _add_group(conn, "Live Group", 10)
    _add_group(conn, "Gone Group", 99)
    _patch_dispatcharr(monkeypatch, [10, 20, 30])  # 99 is gone

    stale = detect_stale_groups(_factory(conn))

    assert {g["name"] for g in stale} == {"Gone Group"}
    live = conn.execute(
        "SELECT source_missing, source_last_seen FROM event_epg_groups WHERE name='Live Group'"
    ).fetchone()
    assert live["source_missing"] == 0
    assert live["source_last_seen"] is not None  # present source refreshed
    gone = conn.execute(
        "SELECT source_missing FROM event_epg_groups WHERE name='Gone Group'"
    ).fetchone()
    assert gone["source_missing"] == 1


def test_channel_source_group_excluded(monkeypatch):
    conn = _db()
    _add_group(conn, "System Source", 99, is_channel_source=1)
    _patch_dispatcharr(monkeypatch, [10])
    assert detect_stale_groups(_factory(conn)) == []


def test_group_without_m3u_source_skipped(monkeypatch):
    conn = _db()
    _add_group(conn, "League Only", None)
    _patch_dispatcharr(monkeypatch, [10])
    assert detect_stale_groups(_factory(conn)) == []


def test_empty_group_list_flags_nothing(monkeypatch):
    """A connection blip (no groups returned) must not flag everything stale."""
    conn = _db()
    _add_group(conn, "Gone Group", 99)
    _patch_dispatcharr(monkeypatch, [])

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT source_missing FROM event_epg_groups WHERE name='Gone Group'"
    ).fetchone()
    assert row["source_missing"] == 0


def test_list_groups_error_flags_nothing(monkeypatch):
    conn = _db()
    _add_group(conn, "Gone Group", 99)

    import teamarr.consumers.source_lifecycle.missing as reconciliation

    def boom():
        raise RuntimeError("dispatcharr down")

    fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=boom))
    monkeypatch.setattr(reconciliation, "get_dispatcharr_connection", lambda db_factory=None: fake)

    assert detect_stale_groups(_factory(conn)) == []


def test_recreated_under_new_id_is_not_stale_and_heals(monkeypatch):
    """Source deleted + recreated (same name, new id) is NOT stale; id self-heals."""
    conn = _db()
    _add_group(conn, "Recreated", 99, m3u_group_name="USA | NCAA BASEBALL")
    source_id = conn.execute("SELECT id FROM event_epg_groups WHERE name='Recreated'").fetchone()[0]
    conn.execute(
        "INSERT INTO source_candidates "
        "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
        "VALUES (99, 'USA | NCAA BASEBALL', 0, 'accepted', ?)",
        (source_id,),
    )
    conn.commit()
    _patch_dispatcharr(monkeypatch, [(500, "USA | NCAA BASEBALL")])  # same name, new id

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT source_missing, m3u_group_id FROM event_epg_groups WHERE name='Recreated'"
    ).fetchone()
    assert row["source_missing"] == 0
    assert row["m3u_group_id"] == 500  # healed to the live id
    cand = conn.execute(
        "SELECT m3u_group_id FROM source_candidates WHERE source_group_id = ?",
        (source_id,),
    ).fetchone()
    assert cand["m3u_group_id"] == 500


def _link_candidates(conn):
    """Give every source the accepted candidate row a discovered source has."""
    conn.execute(
        "INSERT INTO source_candidates "
        "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
        "SELECT m3u_group_id, m3u_group_name, COALESCE(m3u_account_id, 0), 'accepted', id "
        "FROM event_epg_groups"
    )
    conn.commit()


def _bindings(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT g.name, g.m3u_group_id, g.m3u_group_name, g.source_missing, c.m3u_group_id "
            "FROM event_epg_groups g LEFT JOIN source_candidates c ON c.source_group_id = g.id "
            "ORDER BY g.id"
        )
    ]


@pytest.mark.parametrize("managed", [0, 1])
def test_another_day_of_a_rotating_family_is_not_a_heal(monkeypatch, managed):
    """The per-run pass heals by exact name only (#1265).

    `(Thu)` is not `(Wed)`: following a look-alike is the daily scan's call,
    which knows about dismissals and about installs with a source per day.
    """
    conn = _db()
    _add_group(conn, "NHL Source", 71, m3u_group_name="LIVE | NHL (Wed)", m3u_account_id=1)
    conn.execute("UPDATE event_epg_groups SET managed = ?", (managed,))
    _link_candidates(conn)
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL (Thu)", [1])])

    assert [g["name"] for g in detect_stale_groups(_factory(conn))] == ["NHL Source"]
    assert _bindings(conn) == [("NHL Source", 71, "LIVE | NHL (Wed)", 1, 71)]


def test_each_day_source_only_takes_its_own_day(monkeypatch):
    """Three sources of one family: a returning day goes to the source named for it.

    With the look-alike rule the lowest row took whatever day came back and
    the day's own source was then blocked (#1265).
    """
    conn = _db()
    for day, gid in (("Mon", 10), ("Fri", 11), ("Sun", 12)):
        _add_group(conn, f"EPL {day}", gid, m3u_group_name=f"LIVE | EPL ({day})", m3u_account_id=3)
    _link_candidates(conn)
    _patch_dispatcharr(monkeypatch, [(50, "LIVE | EPL (Fri)", [3])])

    assert [g["name"] for g in detect_stale_groups(_factory(conn))] == ["EPL Mon", "EPL Sun"]
    assert _bindings(conn) == [
        ("EPL Mon", 10, "LIVE | EPL (Mon)", 1, 10),
        ("EPL Fri", 50, "LIVE | EPL (Fri)", 0, 50),
        ("EPL Sun", 12, "LIVE | EPL (Sun)", 1, 12),
    ]
    # Stable: a second run changes nothing.
    detect_stale_groups(_factory(conn))
    assert [b[1] for b in _bindings(conn)] == [10, 50, 12]


_ACCOUNT_SHAPES = {
    "ints": lambda count: [1],
    "dicts": lambda count: [{"m3u_account": 1, "stream_count": count}],
    "absent": lambda count: [{"stream_count": count}],
    "none": lambda count: [],
}


@pytest.mark.parametrize("shape", list(_ACCOUNT_SHAPES))
@pytest.mark.parametrize("streams", [8, 0])
def test_exact_name_heal_does_not_depend_on_the_listing_shape(monkeypatch, shape, streams):
    """Same name, new id heals whatever the listing says about accounts.

    A recreated group has no streams until the provider's next refresh, and a
    newer Dispatcharr lists counts with no account ids; gating the heal on
    account membership refused exactly that group (#1265).
    """
    conn = _db()
    _add_group(conn, "NHL", 71, m3u_group_name="LIVE | NHL", m3u_account_id=1)
    _link_candidates(conn)
    lookups = []

    def get_counts(account_id):
        lookups.append(account_id)
        return {}

    _patch_dispatcharr(
        monkeypatch,
        [(72, "LIVE | NHL", _ACCOUNT_SHAPES[shape](streams))],
        get_account_group_counts=get_counts,
    )

    assert detect_stale_groups(_factory(conn)) == []
    assert _bindings(conn) == [("NHL", 72, "LIVE | NHL", 0, 72)]
    assert lookups == []  # the heal asks Dispatcharr nothing more


def test_exact_name_heal_does_not_read_the_listing_account(monkeypatch):
    """As before the rotating work: the name alone decides, also for a scoped source."""
    conn = _db()
    _add_group(conn, "NHL", 71, m3u_group_name="LIVE | NHL (Wed)", m3u_account_id=1)
    _patch_dispatcharr(
        monkeypatch,
        [(72, "LIVE | NHL (Wed)", [2]), (73, "LIVE | NHL (Thu)", [1])],
    )

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT m3u_group_id, m3u_group_name, source_missing FROM event_epg_groups"
    ).fetchone()
    assert tuple(row) == (72, "LIVE | NHL (Wed)", 0)


def test_two_accounts_heal_onto_the_same_recreated_group(monkeypatch):
    conn = _db()
    _add_group(conn, "NHL A", 71, m3u_group_name="LIVE | NHL (Wed)", m3u_account_id=1)
    _add_group(conn, "NHL B", 71, m3u_group_name="LIVE | NHL (Wed)", m3u_account_id=2)
    _link_candidates(conn)
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL (Wed)", [1, 2])])

    assert detect_stale_groups(_factory(conn)) == []
    assert _bindings(conn) == [
        ("NHL A", 72, "LIVE | NHL (Wed)", 0, 72),
        ("NHL B", 72, "LIVE | NHL (Wed)", 0, 72),
    ]


def test_exact_name_heal_merges_the_scans_row_for_the_returned_group(monkeypatch):
    """A scan that saw the new id first left a 'new' row; the heal folds it in."""
    conn = _db()
    _add_group(conn, "NHL", 71, m3u_group_name="LIVE | NHL", m3u_account_id=1)
    _link_candidates(conn)
    kept = conn.execute("SELECT id FROM source_candidates").fetchone()[0]
    conn.execute(
        "INSERT INTO source_candidates (m3u_group_id, m3u_group_name, m3u_account_id, status) "
        "VALUES (72, 'LIVE | NHL', 1, 'new')"
    )
    stray = conn.execute("SELECT id FROM source_candidates WHERE m3u_group_id = 72").fetchone()[0]
    conn.execute(
        "INSERT INTO source_candidate_scans (candidate_id, scanned_at, game_matches) "
        "VALUES (?, '2026-11-01 11:00:00', 2), (?, '2026-11-02 11:00:00', 3)",
        (kept, stray),
    )
    conn.commit()
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL", [1])])

    assert detect_stale_groups(_factory(conn)) == []
    rows = conn.execute(
        "SELECT id, m3u_group_id, status, source_group_id FROM source_candidates"
    ).fetchall()
    assert [tuple(r)[:3] for r in rows] == [(kept, 72, "accepted")]
    scans = conn.execute("SELECT candidate_id FROM source_candidate_scans").fetchall()
    assert [s[0] for s in scans] == [kept, kept]


@pytest.mark.parametrize(
    "first_account, second_account, second_heals",
    [(1, 1, False), (None, 1, False), (1, None, False), (None, None, False), (1, 2, True)],
)
def test_two_sources_never_share_a_group_and_account(
    monkeypatch, first_account, second_account, second_heals
):
    """A heal is refused when another source already reads those streams there.

    An account-less source reads the whole group, so it shares with anyone.
    """
    conn = _db()
    _add_group(conn, "Holder", 72, m3u_group_name="LIVE | NHL", m3u_account_id=first_account)
    _add_group(conn, "Lost", 71, m3u_group_name="LIVE | NHL", m3u_account_id=second_account)
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL", [1, 2])])

    stale = [g["name"] for g in detect_stale_groups(_factory(conn))]
    row = conn.execute(
        "SELECT m3u_group_id, source_missing FROM event_epg_groups WHERE name = 'Lost'"
    ).fetchone()
    assert tuple(row) == ((72, 0) if second_heals else (71, 1))
    assert stale == ([] if second_heals else ["Lost"])


def test_a_disabled_source_on_the_group_does_not_block_the_heal(monkeypatch):
    """A disabled source reads nothing; the enabled one that replaced it still heals."""
    conn = _db()
    _add_group(conn, "Old", 72, m3u_group_name="LIVE | NHL", m3u_account_id=1, enabled=0)
    _add_group(conn, "Lost", 71, m3u_group_name="LIVE | NHL", m3u_account_id=1)
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL", [1])])

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT m3u_group_id, source_missing FROM event_epg_groups WHERE name = 'Lost'"
    ).fetchone()
    assert tuple(row) == (72, 0)


def test_two_lost_sources_of_one_name_heal_in_id_order(monkeypatch):
    """Both lost the id and want the same pair: the lower id gets it, every run."""
    conn = _db()
    _add_group(conn, "Second", 71, m3u_group_name="LIVE | NHL", m3u_account_id=1)
    _add_group(conn, "First", 70, m3u_group_name="LIVE | NHL", m3u_account_id=1)
    conn.execute("UPDATE event_epg_groups SET id = id + 10 WHERE name = 'Second'")
    conn.commit()
    _patch_dispatcharr(monkeypatch, [(72, "LIVE | NHL", [1])])

    for _ in range(2):
        assert [g["name"] for g in detect_stale_groups(_factory(conn))] == ["Second"]
        rows = conn.execute(
            "SELECT name, m3u_group_id, source_missing FROM event_epg_groups ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("First", 72, 0), ("Second", 71, 1)]


def test_exact_name_heal_keeps_source_and_candidate_in_sync_on_conflict(monkeypatch):
    conn = _db()
    _add_group(conn, "Missing", 71, m3u_group_name="NHL", m3u_account_id=1)
    _add_group(conn, "Other", 73, m3u_group_name="Other", m3u_account_id=1)
    conn.execute(
        "INSERT INTO source_candidates "
        "(m3u_group_id, m3u_group_name, m3u_account_id, status, source_group_id) "
        "SELECT CASE WHEN name = 'Missing' THEN 71 ELSE 72 END, 'NHL', 1, 'accepted', id "
        "FROM event_epg_groups"
    )
    conn.commit()
    _patch_dispatcharr(monkeypatch, [(72, "NHL", [1]), (73, "Other", [1])])

    assert [row["name"] for row in detect_stale_groups(_factory(conn))] == ["Missing"]
    rows = conn.execute(
        "SELECT g.name, g.m3u_group_id, c.m3u_group_id "
        "FROM event_epg_groups g JOIN source_candidates c ON c.source_group_id = g.id "
        "ORDER BY g.name"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("Missing", 71, 71), ("Other", 73, 72)]


def test_ambiguous_name_not_healed_but_not_stale(monkeypatch):
    """Two live groups share the name: don't heal (ambiguous), but not stale either."""
    conn = _db()
    _add_group(conn, "Dup", 99, m3u_group_name="Dup Name")
    _patch_dispatcharr(monkeypatch, [(500, "Dup Name"), (501, "Dup Name")])

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT source_missing, m3u_group_id FROM event_epg_groups WHERE name='Dup'"
    ).fetchone()
    assert row["source_missing"] == 0
    assert row["m3u_group_id"] == 99  # left untouched (ambiguous)


def test_recovery_clears_stale_flag(monkeypatch):
    """Once the source reappears, the group is no longer stale."""
    conn = _db()
    _add_group(conn, "Flaky Group", 99)

    _patch_dispatcharr(monkeypatch, [10])  # gone
    assert {g["name"] for g in detect_stale_groups(_factory(conn))} == {"Flaky Group"}

    _patch_dispatcharr(monkeypatch, [99])  # back
    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT source_missing FROM event_epg_groups WHERE name='Flaky Group'"
    ).fetchone()
    assert row["source_missing"] == 0


def test_stale_account_id_auto_healed(monkeypatch):
    """Stale m3u_account_id is auto-healed when account name matches live accounts."""
    conn = _db()
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, m3u_group_id, m3u_account_id, m3u_account_name) "
        "VALUES ('Stale Acc', '[]', 10, 999, 'Provider A')"
    )
    conn.commit()

    import teamarr.consumers.source_lifecycle.missing as reconciliation

    fake_m3u = SimpleNamespace(
        list_groups=lambda: [SimpleNamespace(id=10, name="live-10")],
        list_accounts=lambda: [SimpleNamespace(id=7, name="Provider A")],
    )
    fake = SimpleNamespace(m3u=fake_m3u)
    monkeypatch.setattr(reconciliation, "get_dispatcharr_connection", lambda db_factory=None: fake)

    detect_stale_groups(_factory(conn))

    row = conn.execute(
        "SELECT m3u_account_id FROM event_epg_groups WHERE name='Stale Acc'"
    ).fetchone()
    assert row["m3u_account_id"] == 7


# ---------------------------------------------------------------------------
# Channel-source rows (#1046)
# ---------------------------------------------------------------------------


def _add_channel_source(conn, name, dp_group_id, *, enabled=1):
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, enabled, is_channel_source, dispatcharr_channel_group_id) "
        "VALUES (?, '[]', ?, 1, ?)",
        (name, enabled, dp_group_id),
    )
    conn.commit()


def _missing(conn, name):
    return conn.execute(
        "SELECT source_missing FROM event_epg_groups WHERE name = ?", (name,)
    ).fetchone()[0]


def test_channel_source_whose_group_is_gone_is_flagged_but_never_stale(monkeypatch):
    conn = _db()
    _add_channel_source(conn, "Dispatcharr Channels: 10 SPORTS", 470)
    _add_channel_source(conn, "Dispatcharr Channels: NBA Direct", 4331)
    _patch_dispatcharr(monkeypatch, [470, 1222])  # 4331 was deleted in Dispatcharr

    stale = detect_stale_groups(_factory(conn))

    # The stale list is the M3U rebind/delete flow; channel-source rows stay out.
    assert stale == []
    assert _missing(conn, "Dispatcharr Channels: 10 SPORTS") == 0
    assert _missing(conn, "Dispatcharr Channels: NBA Direct") == 1


def test_channel_source_flag_clears_when_the_group_is_back(monkeypatch):
    conn = _db()
    _add_channel_source(conn, "Dispatcharr Channels: NBA Direct", 4331)
    conn.execute("UPDATE event_epg_groups SET source_missing = 1")
    _patch_dispatcharr(monkeypatch, [4331])

    detect_stale_groups(_factory(conn))

    assert _missing(conn, "Dispatcharr Channels: NBA Direct") == 0


def test_catch_all_channel_source_is_always_present(monkeypatch):
    conn = _db()
    _add_channel_source(conn, "Dispatcharr Channels", None)
    _patch_dispatcharr(monkeypatch, [1])

    detect_stale_groups(_factory(conn))

    assert _missing(conn, "Dispatcharr Channels") == 0


def test_channel_source_is_not_flagged_on_a_dispatcharr_blip(monkeypatch):
    conn = _db()
    _add_channel_source(conn, "Dispatcharr Channels: NBA Direct", 4331)
    _patch_dispatcharr(monkeypatch, [])

    detect_stale_groups(_factory(conn))

    assert _missing(conn, "Dispatcharr Channels: NBA Direct") == 0


# ---------------------------------------------------------------------------
# Remove: a hand-made source whose group has been missing for N days (#1058)
# ---------------------------------------------------------------------------


def _add_source(conn, name, m3u_group_id, *, seen_days_ago=None, managed=0, is_channel_source=0):
    seen = f"datetime('now', '-{seen_days_ago} days')" if seen_days_ago is not None else "NULL"
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, m3u_group_id, enabled, managed, is_channel_source, source_last_seen) "
        f"VALUES (?, '[]', ?, 1, ?, ?, {seen})",
        (name, m3u_group_id, managed, is_channel_source),
    )
    conn.commit()


def _names(conn):
    return {r[0] for r in conn.execute("SELECT name FROM event_epg_groups")}


def _set_delete_days(conn, days):
    conn.execute("UPDATE settings SET source_missing_delete_days = ?", (days,))
    conn.commit()


def test_missing_sources_are_kept_by_default(monkeypatch):
    conn = _db()
    _add_source(conn, "Gone for ages", 99, seen_days_ago=40)
    _patch_dispatcharr(monkeypatch, [10])

    detect_stale_groups(_factory(conn))

    assert "Gone for ages" in _names(conn)
    assert _missing(conn, "Gone for ages") == 1


def test_missing_source_is_deleted_after_the_policy_days(monkeypatch):
    conn = _db()
    _set_delete_days(conn, 3)
    _add_source(conn, "Gone five days", 99, seen_days_ago=5)
    _add_source(conn, "Gone one day", 98, seen_days_ago=1)
    _add_source(conn, "Still here", 10, seen_days_ago=5)
    _patch_dispatcharr(monkeypatch, [10])

    detect_stale_groups(_factory(conn))

    assert _names(conn) == {"Gone one day", "Still here"}
    assert _missing(conn, "Gone one day") == 1
    assert _missing(conn, "Still here") == 0


def test_rule_never_guesses_about_a_source_never_seen(monkeypatch):
    # No recorded last-seen time means no measurable absence: left alone.
    conn = _db()
    _set_delete_days(conn, 1)
    _add_source(conn, "Never seen", 99, seen_days_ago=None)
    _patch_dispatcharr(monkeypatch, [10])

    detect_stale_groups(_factory(conn))

    assert "Never seen" in _names(conn)


def test_rule_leaves_managed_and_channel_source_rows_to_their_own_passes(monkeypatch):
    conn = _db()
    _set_delete_days(conn, 1)
    _add_source(conn, "Managed", 99, seen_days_ago=30, managed=1)
    _add_source(conn, "Channel source", None, seen_days_ago=30, is_channel_source=1)
    conn.execute(
        "UPDATE event_epg_groups SET dispatcharr_channel_group_id = 4331 "
        "WHERE name = 'Channel source'"
    )
    conn.commit()
    _patch_dispatcharr(monkeypatch, [10])

    detect_stale_groups(_factory(conn))

    assert {"Managed", "Channel source"} <= _names(conn)


def test_rule_does_nothing_on_a_dispatcharr_blip(monkeypatch):
    conn = _db()
    _set_delete_days(conn, 1)
    _add_source(conn, "Gone", 99, seen_days_ago=30)
    conn.execute("UPDATE event_epg_groups SET source_missing = 1")
    conn.commit()
    _patch_dispatcharr(monkeypatch, [])

    detect_stale_groups(_factory(conn))

    assert "Gone" in _names(conn)


def test_policy_reads_the_settings_row():
    from teamarr.consumers.source_lifecycle import load_policy

    conn = _db()
    conn.execute(
        "UPDATE settings SET source_idle_days = 5, source_gone_days = 9, "
        "source_missing_delete_days = 2, source_discovery_mode = 'off'"
    )
    conn.commit()

    policy = load_policy(conn)

    assert (policy.idle_days, policy.idle_days_named, policy.gone_days) == (5, 12, 9)
    assert policy.missing_delete_days == 2
    assert policy.discovery_enabled is False
