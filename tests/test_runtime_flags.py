"""#554 — SCHEDULER=off / DRY_RUN=true runtime flags.

Env-only flags that make a second Teamarr instance safe beside production:
the scheduler never starts, and every outbound write is logged, not executed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.config import runtime
from teamarr.dispatcharr.client import DispatcharrClient

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [(None, True), ("", True), ("on", True), ("1", True), ("anything", True),
     ("off", False), ("OFF", False), ("0", False), ("false", False), ("no", False),
     (" off ", False)],
)
def test_scheduler_enabled_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SCHEDULER", raising=False)
    else:
        monkeypatch.setenv("SCHEDULER", value)
    assert runtime.scheduler_enabled() is expected


@pytest.mark.parametrize(
    "value,expected",
    [(None, False), ("", False), ("false", False), ("0", False), ("off", False),
     ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True)],
)
def test_dry_run_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("DRY_RUN", value)
    assert runtime.dry_run() is expected


def test_runtime_flags_shape(monkeypatch):
    monkeypatch.setenv("SCHEDULER", "off")
    monkeypatch.setenv("DRY_RUN", "true")
    assert runtime.runtime_flags() == {"scheduler_enabled": False, "dry_run": True}


def test_health_reports_runtime(monkeypatch):
    monkeypatch.setenv("SCHEDULER", "off")
    monkeypatch.delenv("DRY_RUN", raising=False)
    from teamarr.api.routes.health import health_check

    body = health_check()
    assert body["runtime"] == {"scheduler_enabled": False, "dry_run": False}


# ---------------------------------------------------------------------------
# Dispatcharr write chokepoint
# ---------------------------------------------------------------------------


def _client_with_spy():
    """A DispatcharrClient whose HTTP layer records calls instead of sending."""
    client = DispatcharrClient.__new__(DispatcharrClient)
    client._base_url = "http://dp.test"
    client._max_retries = 0
    client._auth = MagicMock()
    client._auth.get_token.return_value = "tok"
    http = MagicMock()
    ok = MagicMock(status_code=200)
    ok.json.return_value = {}
    for m in ("get", "post", "patch", "delete"):
        getattr(http, m).return_value = ok
    client._get_client = lambda: http
    return client, http


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_dry_run_suppresses_mutations(monkeypatch, method, caplog):
    monkeypatch.setenv("DRY_RUN", "true")
    client, http = _client_with_spy()
    with caplog.at_level("INFO"):
        resp = client.request(method, "/api/channels/channels/", {"name": "x"})
    assert resp is None
    assert not http.post.called and not http.patch.called and not http.delete.called
    assert client._auth.get_token.call_count == 0  # never even authenticates
    assert any("[DRY_RUN] Suppressed" in r.message and method in r.message for r in caplog.records)


def test_dry_run_allows_reads(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    client, http = _client_with_spy()
    assert client.request("GET", "/api/channels/channels/") is not None
    assert http.get.called


def test_writes_go_through_when_not_dry_run(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    client, http = _client_with_spy()
    assert client.request("POST", "/api/channels/channels/", {"name": "x"}) is not None
    assert http.post.called


def test_dry_run_error_message_is_explicit(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    client, _ = _client_with_spy()
    assert "DRY_RUN" in client.parse_api_error(None)
    monkeypatch.delenv("DRY_RUN")
    assert "DRY_RUN" not in client.parse_api_error(None)


# ---------------------------------------------------------------------------
# Media-server refreshes
# ---------------------------------------------------------------------------


def test_dry_run_media_refresh_records_and_skips(monkeypatch):
    from teamarr.consumers.generation import _dry_run_media_refresh

    monkeypatch.setenv("DRY_RUN", "true")
    result = SimpleNamespace(
        emby_refresh={}, jellyfin_refresh={}, channelsdvr_refresh={}, channelsdvr_epg_refresh={}
    )
    jobs = [
        ("emby", SimpleNamespace(url="http://emby:8096")),
        ("channelsdvr", SimpleNamespace(url="http://cdvr:8089")),
    ]
    assert _dry_run_media_refresh(result, jobs) is True
    assert result.emby_refresh == {
        "success": True, "dry_run": True, "servers": ["http://emby:8096"],
    }
    assert result.channelsdvr_refresh["dry_run"] is True
    assert result.channelsdvr_epg_refresh["dry_run"] is True
    assert result.jellyfin_refresh == {}


def test_media_refresh_runs_when_not_dry_run(monkeypatch):
    from teamarr.consumers.generation import _dry_run_media_refresh

    monkeypatch.delenv("DRY_RUN", raising=False)
    result = SimpleNamespace(emby_refresh={})
    assert _dry_run_media_refresh(result, [("emby", SimpleNamespace(url="u"))]) is False
    assert result.emby_refresh == {}


# ---------------------------------------------------------------------------
# Scheduler gate (startup)
# ---------------------------------------------------------------------------


def test_scheduler_off_gate_matches_startup_condition(monkeypatch):
    """The startup phase starts the scheduler only when BOTH the DB setting and
    the env flag allow it (app.py); this pins the env half of that condition."""
    monkeypatch.setenv("SCHEDULER", "off")
    db_enabled = True
    assert not (db_enabled and runtime.scheduler_enabled())
    monkeypatch.setenv("SCHEDULER", "on")
    assert db_enabled and runtime.scheduler_enabled()
