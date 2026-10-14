"""Stale source-group detection (lylt.1).

A group is stale when its Dispatcharr M3U source channel-group no longer
exists. Off-season (group still exists, zero streams) must NOT be flagged, and
a Dispatcharr blip (empty/failed group list) must flag nothing.
"""

import contextlib
import sqlite3
from types import SimpleNamespace

from teamarr.consumers.reconciliation import detect_stale_groups
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


def _add_group(conn, name, m3u_group_id, *, enabled=1, is_channel_source=0, m3u_group_name=None):
    conn.execute(
        "INSERT INTO event_epg_groups "
        "(name, leagues, m3u_group_id, m3u_group_name, enabled, is_channel_source) "
        "VALUES (?, '[]', ?, ?, ?, ?)",
        (name, m3u_group_id, m3u_group_name, enabled, is_channel_source),
    )
    conn.commit()


def _patch_dispatcharr(monkeypatch, groups):
    """Fake get_dispatcharr_connection -> .m3u.list_groups().

    `groups` items may be ints (auto-named) or (id, name) tuples.
    """
    import teamarr.consumers.reconciliation as reconciliation

    def mk(item):
        if isinstance(item, tuple):
            return SimpleNamespace(id=item[0], name=item[1])
        return SimpleNamespace(id=item, name=f"live-{item}")

    fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=lambda: [mk(i) for i in groups]))
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

    import teamarr.consumers.reconciliation as reconciliation

    def boom():
        raise RuntimeError("dispatcharr down")

    fake = SimpleNamespace(m3u=SimpleNamespace(list_groups=boom))
    monkeypatch.setattr(reconciliation, "get_dispatcharr_connection", lambda db_factory=None: fake)

    assert detect_stale_groups(_factory(conn)) == []


def test_recreated_under_new_id_is_not_stale_and_heals(monkeypatch):
    """Source deleted + recreated (same name, new id) is NOT stale; id self-heals."""
    conn = _db()
    _add_group(conn, "Recreated", 99, m3u_group_name="USA | NCAA BASEBALL")
    _patch_dispatcharr(monkeypatch, [(500, "USA | NCAA BASEBALL")])  # same name, new id

    assert detect_stale_groups(_factory(conn)) == []
    row = conn.execute(
        "SELECT source_missing, m3u_group_id FROM event_epg_groups WHERE name='Recreated'"
    ).fetchone()
    assert row["source_missing"] == 0
    assert row["m3u_group_id"] == 500  # healed to the live id


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

    import teamarr.consumers.reconciliation as reconciliation

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
