"""Regression tests for #511: API timestamps must carry an explicit offset.

SQLite-canonical naive UTC strings (``datetime('now')``/``CURRENT_TIMESTAMP``)
serialized verbatim reach the browser offset-less; JS ``new Date()`` then
parses them as browser-LOCAL time and the UI echoes raw UTC digits (the
"deleted at 3:01 AM" report from Brisbane).
"""

from datetime import UTC, datetime

from teamarr.api.routes.channels import _safe_isoformat
from teamarr.database.templates import _parse_ts


class TestSafeIsoformat:
    def test_naive_db_string_gains_utc_offset(self):
        assert _safe_isoformat("2026-07-25 03:01:00") == "2026-07-25T03:01:00+00:00"

    def test_aware_string_keeps_instant(self):
        out = _safe_isoformat("2026-07-25T13:01:00+10:00")
        assert out is not None
        assert datetime.fromisoformat(out) == datetime.fromisoformat("2026-07-25T03:01:00+00:00")

    def test_aware_datetime_object_passthrough(self):
        dt = datetime(2026, 7, 25, 3, 1, tzinfo=UTC)
        assert _safe_isoformat(dt) == "2026-07-25T03:01:00+00:00"

    def test_none_and_garbage(self):
        assert _safe_isoformat(None) is None
        assert _safe_isoformat("not a timestamp") == "not a timestamp"


class TestTemplateParseTs:
    def test_naive_db_string_becomes_aware_utc(self):
        parsed = _parse_ts("2026-07-25 03:01:00")
        assert parsed == datetime(2026, 7, 25, 3, 1, tzinfo=UTC)
        assert parsed.isoformat() == "2026-07-25T03:01:00+00:00"

    def test_none_and_garbage(self):
        assert _parse_ts(None) is None
        assert _parse_ts("garbage") is None


def test_group_row_timestamps_parse_aware(db_conn):
    """last_refresh/updated_at come back timezone-aware so route .isoformat()
    emits an offset."""
    from teamarr.database.groups import create_group, get_group, update_group_stats

    gid = create_group(db_conn, name="TZ Test", leagues=["nfl"])
    update_group_stats(db_conn, gid, stream_count=1, matched_count=1)
    group = get_group(db_conn, gid)
    assert group is not None
    assert group.last_refresh is not None
    assert group.last_refresh.tzinfo is not None
    assert "+" in group.last_refresh.isoformat() or group.last_refresh.isoformat().endswith(
        "+00:00"
    )
