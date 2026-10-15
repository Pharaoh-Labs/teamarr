"""managed_channel_history accepts every change_source the code writes (#1065).

The team-filter delete path logged ``team_filter`` (since 2026-01) and
``template_assignment`` (#1061); neither was in the schema CHECK, so the
history insert threw after the soft delete and the Dispatcharr delete behind
it never ran. The pre-migration rebuilds the table for existing databases;
the literal scan keeps the next new deleter from repeating this.
"""

import re
import sqlite3
from pathlib import Path

from teamarr.database.migrations import (
    _migrate_channel_history_check,
    _migrate_channel_history_restore_if_needed,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "teamarr" / "database" / "schema.sql"


def _schema_check_values() -> set[str]:
    sql = SCHEMA.read_text()
    block = sql[sql.index("CREATE TABLE IF NOT EXISTS managed_channel_history") :]
    m = re.search(r"change_source TEXT\s+CHECK\(change_source IN \(([^)]*)\)\)", block)
    assert m, "change_source CHECK not found in schema.sql"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _history_table_sql(values: set[str]) -> str:
    quoted = ", ".join(f"'{v}'" for v in sorted(values))
    return f"""
        CREATE TABLE managed_channel_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            managed_channel_id INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            change_source TEXT CHECK(change_source IN ({quoted})),
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """


def test_every_change_source_literal_is_accepted_by_schema():
    allowed = _schema_check_values()
    used: dict[str, str] = {}
    for path in (ROOT / "teamarr").rglob("*.py"):
        text = path.read_text()
        for m in re.finditer(r"change_source\s*[=:]\s*[\"']([a-z_]+)[\"']", text):
            used[m.group(1)] = str(path.relative_to(ROOT))
        # keyword default on a function signature
        for m in re.finditer(r"change_source:\s*str\s*=\s*[\"']([a-z_]+)[\"']", text):
            used[m.group(1)] = str(path.relative_to(ROOT))
    missing = {v: f for v, f in used.items() if v not in allowed}
    assert not missing, f"change_source values not in schema CHECK: {missing}"
    assert {"team_filter", "template_assignment"} <= allowed


def test_stale_check_is_rebuilt_and_rows_survive():
    stale = _schema_check_values() - {"team_filter", "template_assignment"}
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE managed_channels (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO managed_channels (id) VALUES (7)")
    conn.execute(_history_table_sql(stale))
    conn.execute(
        "INSERT INTO managed_channel_history "
        "(managed_channel_id, change_type, change_source, notes) "
        "VALUES (7, 'created', 'lifecycle', 'keep me')"
    )
    # Documents the bug: the team-filter signature is rejected on the old table.
    try:
        conn.execute(
            "INSERT INTO managed_channel_history (managed_channel_id, change_type, change_source) "
            "VALUES (7, 'deleted', 'template_assignment')"
        )
        rejected = False
    except sqlite3.IntegrityError:
        rejected = True
    assert rejected

    _migrate_channel_history_check(conn)
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='managed_channel_history'"
    ).fetchone()[0]

    # executescript recreates the table from schema.sql with the current CHECK
    conn.execute(_history_table_sql(_schema_check_values()))
    _migrate_channel_history_restore_if_needed(conn)

    rows = conn.execute(
        "SELECT id, managed_channel_id, change_source, notes FROM managed_channel_history"
    ).fetchall()
    assert rows == [(1, 7, "lifecycle", "keep me")]
    for value in ("team_filter", "template_assignment"):
        conn.execute(
            "INSERT INTO managed_channel_history (managed_channel_id, change_type, change_source) "
            "VALUES (7, 'deleted', ?)",
            (value,),
        )
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='_managed_channel_history_backup'"
    ).fetchone()[0]


def test_rebuild_skipped_when_check_current():
    conn = sqlite3.connect(":memory:")
    conn.execute(_history_table_sql(_schema_check_values()))
    conn.execute(
        "INSERT INTO managed_channel_history (managed_channel_id, change_type, change_source) "
        "VALUES (1, 'created', 'lifecycle')"
    )
    _migrate_channel_history_check(conn)
    assert conn.execute("SELECT COUNT(*) FROM managed_channel_history").fetchone()[0] == 1


def test_init_db_rebuilds_a_real_database(tmp_path):
    """End to end through init_db: an old-CHECK table on disk comes out current."""
    from teamarr.database.connection import init_db

    db = tmp_path / "t.db"
    init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO managed_channels (id, event_id, event_provider, tvg_id, channel_name) "
        "VALUES (3, 'e1', 'espn', 'tvg', 'MLB | MIL/LAD')"
    )
    conn.execute("DROP TABLE managed_channel_history")
    stale = _schema_check_values() - {"team_filter", "template_assignment"}
    conn.execute(_history_table_sql(stale))
    conn.execute(
        "INSERT INTO managed_channel_history (managed_channel_id, change_type, change_source) "
        "VALUES (3, 'created', 'lifecycle'), (999, 'created', 'lifecycle')"
    )
    conn.commit()
    conn.close()

    init_db(db)
    conn = sqlite3.connect(db)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='managed_channel_history'"
    ).fetchone()[0]
    assert "template_assignment" in sql
    # The live channel's row survives; the orphan (no channel 999) is dropped
    # rather than failing the restore.
    survivors = conn.execute("SELECT managed_channel_id FROM managed_channel_history").fetchall()
    assert survivors == [(3,)]
    conn.execute(
        "INSERT INTO managed_channel_history (managed_channel_id, change_type, change_source) "
        "VALUES (3, 'deleted', 'team_filter')"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='idx_mch_channel'"
    ).fetchone()[0]
    conn.close()
