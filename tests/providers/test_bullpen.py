"""Regression coverage for Bullpen proxy routing and credential handling."""

import sqlite3
from contextlib import contextmanager

import httpx
import pytest

from teamarr.database.settings import get_bullpen_settings, update_bullpen_settings
from teamarr.database.settings.types import BullpenSettings
from teamarr.providers import _get_bullpen_config
from teamarr.providers.base_client import BaseHTTPClient, BullpenConfig, bullpen_rewrite
from teamarr.providers.espn.client import ESPNClient
from teamarr.providers.nascar.provider import NASCARProvider
from teamarr.providers.tsdb.client import TSDBClient
from tests.helpers import SCHEMA_PATH


class _StubClient(BaseHTTPClient):
    PROVIDER = "stub"
    LOG_TAG = "STUB"


@pytest.mark.parametrize(
    ("origin", "target", "expected"),
    [
        ("https://example.test/feed/", "hockeytech", "https://proxy.test/v1/hockeytech/feed"),
        ("https://example.test/", "squiggle", "https://proxy.test/v1/squiggle"),
    ],
)
def test_bullpen_rewrite_normalizes_trailing_slashes(origin, target, expected):
    bullpen = BullpenConfig(api_key="key", base_url="https://proxy.test/")

    assert bullpen_rewrite(origin, target, bullpen) == expected


def test_bullpen_key_is_only_sent_to_proxy_host():
    requests = []
    client = _StubClient(bullpen=BullpenConfig(api_key="key", base_url="https://proxy.test"))
    client._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200, json={}))[1]
        )
    )

    client._request_json("https://origin.test/direct")
    client._request_json("https://proxy.test/v1/stub/proxied")

    assert "X-Bullpen-Key" not in requests[0].headers
    assert requests[1].headers["X-Bullpen-Key"] == "key"
    client.close()


def test_anonymous_bullpen_request_omits_api_key_header():
    requests = []
    client = _StubClient(bullpen=BullpenConfig(base_url="https://proxy.test"))
    client._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200, json={}))[1]
        )
    )

    client._request_json("https://proxy.test/v1/stub/proxied")

    assert "X-Bullpen-Key" not in requests[0].headers
    client.close()


@pytest.mark.parametrize(
    ("settings", "enabled"),
    [
        (BullpenSettings(), False),
        (BullpenSettings(enabled=True), False),
        (BullpenSettings(enabled=True, api_key="key"), False),
        (BullpenSettings(enabled=True, espn_enabled=True), False),
        (BullpenSettings(enabled=True, bellmedia_enabled=True), True),
    ],
)
def test_bullpen_config_requires_all_enable_conditions(monkeypatch, settings, enabled):
    @contextmanager
    def db():
        yield object()

    monkeypatch.setattr("teamarr.providers.get_db", db)
    monkeypatch.setattr("teamarr.providers.get_bullpen_settings", lambda conn: settings)

    config = _get_bullpen_config("bellmedia_enabled")

    assert (config is not None) is enabled


def test_espn_core_and_nascar_urls_use_bullpen_targets():
    bullpen = BullpenConfig(api_key="key", base_url="https://proxy.test")

    espn = ESPNClient(bullpen=bullpen)
    nascar = NASCARProvider(bullpen=bullpen)

    assert espn._season_group_url("football", "nfl", 2026, "1").startswith(
        "https://proxy.test/v1/espn-core/v2/sports/"
    )
    assert nascar._base_url == "https://proxy.test/v1/nascar/cacher"


def test_bullpen_makes_tsdb_premium():
    assert TSDBClient(bullpen=BullpenConfig(api_key="key")).is_premium is True


def test_bullpen_api_key_can_be_cleared():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("UPDATE settings SET bullpen_api_key = 'key' WHERE id = 1")

    update_bullpen_settings(conn, api_key=None)

    assert get_bullpen_settings(conn).api_key is None


def test_bullpen_disable_status_can_be_cleared():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())

    update_bullpen_settings(
        conn,
        enabled=False,
        disabled_reason="Bullpen returned 401 Unauthorized after three attempts.",
        disabled_at="2026-08-28T12:00:00+00:00",
    )
    update_bullpen_settings(conn, enabled=True, disabled_reason=None, disabled_at=None)

    settings = get_bullpen_settings(conn)
    assert settings.enabled is True
    assert settings.disabled_reason is None
    assert settings.disabled_at is None
