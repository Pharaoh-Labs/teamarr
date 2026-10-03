"""group_templates is gone (#822).

The table held per-source template assignments until the subscription
migration copied them into subscription_templates. It was then described as
"read by nothing", but three things still touched it: a startup statement
re-filled it on every start, the support bundle exported it in place of the
real assignments, and the starter-template retirement check treated its
leftover rows as references. v99 drops it and each of those now reads
subscription_templates.
"""

import json
import sqlite3
import zipfile
from io import BytesIO

from teamarr.database.connection import get_connection
from teamarr.database.default_templates import _is_referenced
from teamarr.database.migrations.versioned import _migrate_v99_drop_group_templates
from teamarr.services.support_bundle import SCHEMA_VERSION, SupportBundleService


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_fresh_database_has_no_group_templates(db_conn):
    assert "group_templates" not in _tables(db_conn)
    assert "subscription_templates" in _tables(db_conn)


def test_migration_drops_the_table_and_its_index():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE group_templates (
            id INTEGER PRIMARY KEY, group_id INTEGER, template_id INTEGER);
        CREATE INDEX idx_group_templates_group_id ON group_templates(group_id);
        INSERT INTO group_templates (group_id, template_id) VALUES (1, 3);
        """
    )
    _migrate_v99_drop_group_templates(conn)
    assert "group_templates" not in _tables(conn)
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'idx_group_templates_group_id'"
    ).fetchone()
    _migrate_v99_drop_group_templates(conn)  # already gone: no error


def test_existing_install_is_upgraded_and_keeps_its_assignments(db_path):
    """An install at v98 with leftover rows: the table goes, the live
    assignments stay, and the database still opens."""
    from teamarr.database import init_db

    with get_connection(db_path) as conn:
        template = conn.execute(
            "INSERT INTO templates (name, template_type) VALUES ('T', 'event')"
        ).lastrowid
        conn.execute(
            "INSERT INTO subscription_templates (template_id, leagues) VALUES (?, ?)",
            (template, '["nfl"]'),
        )
        conn.executescript(
            f"""
            CREATE TABLE group_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
                template_id INTEGER NOT NULL, sports JSON, leagues JSON);
            CREATE INDEX idx_group_templates_group_id ON group_templates(group_id);
            INSERT INTO group_templates (group_id, template_id) VALUES (1, {template});
            UPDATE settings SET schema_version = 98;
            """
        )
        conn.commit()

    init_db(db_path)

    with get_connection(db_path) as conn:
        assert "group_templates" not in _tables(conn)
        assert conn.execute("SELECT schema_version FROM settings").fetchone()[0] == 99
        rows = conn.execute("SELECT template_id, leagues FROM subscription_templates").fetchall()
        assert [(r[0], r[1]) for r in rows] == [(template, '["nfl"]')]


def test_retirement_check_reads_the_live_assignments(db_conn):
    used = db_conn.execute(
        "INSERT INTO templates (name, template_type) VALUES ('Used', 'event')"
    ).lastrowid
    unused = db_conn.execute(
        "INSERT INTO templates (name, template_type) VALUES ('Unused', 'event')"
    ).lastrowid
    db_conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (used,))

    assert _is_referenced(db_conn, used) is True
    assert _is_referenced(db_conn, unused) is False


def test_support_bundle_exports_the_live_assignments(db_path, tmp_path):
    with get_connection(db_path) as conn:
        template = conn.execute(
            "INSERT INTO templates (name, template_type) VALUES ('T', 'event')"
        ).lastrowid
        conn.execute(
            "INSERT INTO subscription_templates (template_id, sports, leagues) VALUES (?, ?, ?)",
            (template, None, '["nfl"]'),
        )
        conn.commit()

    bundle = SupportBundleService(db_path, tmp_path).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        report = json.loads(archive.read("support-report.json"))
        guide = archive.read("AGENTS.md").decode()

    assert SCHEMA_VERSION == 3 and report["schema_version"] == 3
    section = report["sources_and_subscriptions"]
    assert "source_template_mappings" not in section
    assert [row["template_id"] for row in section["template_assignments"]] == [template]
    assert report.get("collection_errors", []) == []
    assert "bundle_schema_version: 3" in guide
