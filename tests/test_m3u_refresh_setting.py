"""The "Refresh M3U accounts before generation" setting (#1120).

On (the default) a generation run and a group preview refresh the Dispatcharr
M3U account first, as they always did. Off, neither does: the generation stage
logs one line and leaves the empty result, and the preview skips its Step 0.
"""

import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.event_group_processor import preview as preview_module
from teamarr.consumers.generation_pipeline.phases import preparation
from teamarr.database.settings import get_dispatcharr_settings, update_dispatcharr_settings

EMPTY_RESULT = {"refreshed": 0, "skipped": 0, "failed": 0, "account_ids": []}


class _Context(SimpleNamespace):
    def report(self, *args):
        pass


def _context(db_factory, client):
    return _Context(
        db_factory=db_factory,
        dispatcharr_client=client,
        result=SimpleNamespace(m3u_refresh={}),
    )


def _set(db_factory, value):
    with db_factory() as conn:
        update_dispatcharr_settings(conn, refresh_m3u_before_generation=value)


# --- setting ---------------------------------------------------------------


def test_default_is_on(db_conn):
    assert get_dispatcharr_settings(db_conn).refresh_m3u_before_generation is True


def test_round_trip_and_untouched_when_not_provided(db_conn):
    update_dispatcharr_settings(db_conn, refresh_m3u_before_generation=False)
    assert get_dispatcharr_settings(db_conn).refresh_m3u_before_generation is False
    # A save that does not mention it (the Output tab) must not switch it back on.
    update_dispatcharr_settings(db_conn, epg_id=12)
    assert get_dispatcharr_settings(db_conn).refresh_m3u_before_generation is False
    update_dispatcharr_settings(db_conn, refresh_m3u_before_generation=True)
    assert get_dispatcharr_settings(db_conn).refresh_m3u_before_generation is True


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.database.connection import init_db

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return TestClient(app)


def test_api_reads_and_writes_the_setting(client):
    url = "/api/v1/settings/dispatcharr"
    key = "refresh_m3u_before_generation"
    assert client.get(url).json()[key] is True

    resp = client.put(url, json={key: False})
    assert resp.status_code == 200, resp.text
    assert resp.json()[key] is False

    # An update that omits it leaves it alone.
    resp = client.put(url, json={"cleanup_unused_logos": True})
    assert resp.json()[key] is False

    resp = client.put(url, json={key: True})
    assert resp.json()[key] is True


# --- generation stage ------------------------------------------------------


def test_stage_refreshes_when_on(db_factory):
    refresh = MagicMock(return_value={"refreshed": 1})
    context = _context(db_factory, object())

    preparation.stage_m3u_refresh(context, refresh_m3u_accounts=refresh)

    refresh.assert_called_once_with(db_factory, context.dispatcharr_client)
    assert context.result.m3u_refresh == {"refreshed": 1}


def test_stage_skips_logs_one_line_and_returns_the_empty_result_when_off(db_factory, caplog):
    _set(db_factory, False)
    refresh = MagicMock()
    context = _context(db_factory, object())

    with caplog.at_level(logging.INFO, logger=preparation.logger.name):
        preparation.stage_m3u_refresh(context, refresh_m3u_accounts=refresh)

    refresh.assert_not_called()
    assert context.result.m3u_refresh == EMPTY_RESULT
    assert len([r for r in caplog.records if "[M3U]" in r.getMessage()]) == 1


# --- preview Step 0 --------------------------------------------------------


@pytest.fixture
def preview(db_factory, monkeypatch):
    client = MagicMock()
    group = SimpleNamespace(name="Group", m3u_account_id=7)
    monkeypatch.setattr(preview_module, "get_group", lambda conn, group_id: group)
    proc = EventGroupProcessor(
        db_factory=db_factory, dispatcharr_client=client, service=MagicMock()
    )
    proc._fetch_streams = lambda group: []
    return proc, client


def test_preview_refreshes_when_on(preview):
    proc, client = preview
    client.m3u.wait_for_refresh.return_value = SimpleNamespace(
        skipped=False, success=True, duration=1.0, message=""
    )
    proc.preview_group(1, date(2026, 10, 22))
    client.m3u.wait_for_refresh.assert_called_once()


def test_preview_skips_step_zero_when_off(preview, db_factory):
    proc, client = preview
    _set(db_factory, False)
    result = proc.preview_group(1, date(2026, 10, 22))
    client.m3u.wait_for_refresh.assert_not_called()
    # The rest of the preview still runs: it got as far as fetching streams.
    assert result.errors == ["No streams found for this source"]
