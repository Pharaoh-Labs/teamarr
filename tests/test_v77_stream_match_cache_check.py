"""v77: stream_match_cache CHECK rebuild — allow 'direct'/'epg' match methods.

RacingMatcher (v2.8.0) and TennisMatcher (mf7) cache matches with
match_method='direct', which the pre-v77 CHECK rejected — every direct-match
cache write failed silently. The rebuild must preserve user-corrected rows
(pinned matches are user data) while discarding disposable algorithmic rows.
"""

import sqlite3

from teamarr.database.connection import (
    _migrate_stream_match_cache_check,
    _migrate_stream_match_cache_restore_if_needed,
)

_OLD_TABLE = """
CREATE TABLE stream_match_cache (
    fingerprint TEXT PRIMARY KEY,
    group_id INTEGER,
    stream_id INTEGER,
    stream_name TEXT,
    event_id TEXT,
    league TEXT,
    cached_data TEXT,
    generation INTEGER,
    match_method TEXT DEFAULT 'fuzzy'
        CHECK(match_method IN ('cache', 'user_corrected', 'alias', 'pattern',
                               'fuzzy', 'keyword', 'no_match')),
    user_corrected BOOLEAN DEFAULT 0,
    corrected_at TIMESTAMP
)
"""

_NEW_TABLE = _OLD_TABLE.replace("'no_match')", "'no_match', 'direct', 'epg')")


def _seed(conn):
    conn.execute(
        "INSERT INTO stream_match_cache "
        "(fingerprint, stream_name, event_id, match_method, user_corrected) "
        "VALUES ('fp-user', 'PINNED', 'e1', 'user_corrected', 1)"
    )
    conn.execute(
        "INSERT INTO stream_match_cache "
        "(fingerprint, stream_name, event_id, match_method, user_corrected) "
        "VALUES ('fp-algo', 'ALGO', 'e2', 'fuzzy', 0)"
    )


def test_old_check_rejects_direct():
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_TABLE)
    try:
        conn.execute(
            "INSERT INTO stream_match_cache (fingerprint, match_method) "
            "VALUES ('x', 'direct')"
        )
        rejected = False
    except sqlite3.IntegrityError:
        rejected = True
    assert rejected  # documents the bug the migration fixes


def test_rebuild_preserves_user_corrections_and_allows_direct():
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_TABLE)
    _seed(conn)

    # Pre-migration: stale CHECK detected → backup corrections, drop table
    _migrate_stream_match_cache_check(conn)
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='stream_match_cache'"
    ).fetchone()[0]
    assert conn.execute(
        "SELECT COUNT(*) FROM _stream_match_cache_backup"
    ).fetchone()[0] == 1  # only the pinned row

    # executescript would recreate with the new CHECK
    conn.execute(_NEW_TABLE)
    _migrate_stream_match_cache_restore_if_needed(conn)

    rows = conn.execute(
        "SELECT fingerprint, user_corrected FROM stream_match_cache"
    ).fetchall()
    assert rows == [("fp-user", 1)]  # pinned survived, algo row discarded

    # 'direct' now inserts cleanly (the original failure mode)
    conn.execute(
        "INSERT INTO stream_match_cache (fingerprint, match_method) "
        "VALUES ('fp-direct', 'direct')"
    )
    # backup cleaned up
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='_stream_match_cache_backup'"
    ).fetchone()[0]


def test_rebuild_skipped_when_check_current():
    conn = sqlite3.connect(":memory:")
    conn.execute(_NEW_TABLE)
    _seed(conn)
    _migrate_stream_match_cache_check(conn)
    # Table untouched
    assert conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 2
