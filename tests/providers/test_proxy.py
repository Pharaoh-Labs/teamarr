"""Regression coverage for provider SOCKS5 policy settings."""

import sqlite3

from teamarr.database.settings import get_proxy_settings, update_proxy_settings
from tests.helpers import SCHEMA_PATH


def test_proxy_url_can_be_cleared():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("UPDATE settings SET proxy_url = 'socks5://proxy.test:1080' WHERE id = 1")
    update_proxy_settings(conn, url=None)
    assert get_proxy_settings(conn).url is None


def test_proxy_exclusions_round_trip():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    update_proxy_settings(conn, enabled=True, excluded_providers=["supabase"])
    settings = get_proxy_settings(conn)
    assert settings.enabled is True
    assert settings.excluded_providers == ["supabase"]
