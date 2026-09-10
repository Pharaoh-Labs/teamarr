"""Reorder-only pass (#576): the ordering step without a generation run.

One endpoint, one button. It takes the generation lock so it can never overlap
a real run, answers 409 while one is in progress, and — being user-triggered —
bypasses the live-event #1 pin exactly like a manual generation (#232).
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers import generation
from teamarr.database import init_db

client = TestClient(app)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def test_apply_runs_the_ordering_step_only(isolated_db, monkeypatch):
    seen: dict = {}

    def fake_apply(db_factory, dispatcharr_client, update_progress, manual=False):
        seen["manual"] = manual
        seen["client"] = dispatcharr_client
        update_progress("ordering", 50, "no-op callback must be callable")
        return {
            "channels_reordered": 3,
            "streams_reordered": 7,
            "windows_synced": 1,
            "order_drift_synced": 2,
            "stats_refreshed": 40,
            "ignored_extra_key": "x",
        }

    monkeypatch.setattr(generation, "_apply_stream_ordering", fake_apply)

    resp = client.post("/api/v1/settings/stream-ordering/apply")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "channels_reordered": 3,
        "streams_reordered": 7,
        "windows_synced": 1,
        "order_drift_synced": 2,
        "stats_refreshed": 40,
    }
    # The button is the escape hatch: it bypasses the live pin like Generate does.
    assert seen["manual"] is True
    # Dispatcharr is not configured in the isolated DB → DB-only pass.
    assert seen["client"] is None


def test_apply_is_409_while_a_generation_holds_the_lock(isolated_db, monkeypatch):
    called = []
    monkeypatch.setattr(
        generation, "_apply_stream_ordering", lambda *a, **k: called.append(1) or {}
    )
    assert generation._generation_lock.acquire(blocking=False)
    try:
        resp = client.post("/api/v1/settings/stream-ordering/apply")
    finally:
        generation._generation_lock.release()
    assert resp.status_code == 409
    assert called == []


def test_lock_is_released_after_a_pass(isolated_db, monkeypatch):
    monkeypatch.setattr(generation, "_apply_stream_ordering", lambda *a, **k: {})
    assert client.post("/api/v1/settings/stream-ordering/apply").status_code == 200
    assert generation._generation_lock.acquire(blocking=False)
    generation._generation_lock.release()
    assert generation._generation_running is False


def test_scheduled_caller_keeps_the_live_pin(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        generation,
        "_apply_stream_ordering",
        lambda db, c, p, manual=False: seen.setdefault("manual", manual) or {},
    )
    generation.run_stream_ordering_only(lambda: None, None, manual=False)
    assert seen["manual"] is False
