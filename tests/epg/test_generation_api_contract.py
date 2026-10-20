"""Characterization of generation's caller-facing contracts (#830, Packet 0).

Three callers must keep working byte-for-byte through the pipeline extraction:

* ``POST /api/v1/epg/generate`` — synchronous response body and status codes.
* ``GET  /api/v1/epg/generate/stream`` — SSE event ordering, frame shape,
  heartbeats and the duplicate-run error frame.
* ``CronScheduler._task_generate_epg`` — the flattened result dictionary.

Every case here patches ``run_full_generation`` itself. The point is to pin the
*translation* each caller performs, independent of what generation does
internally; ``test_generation_contract.py`` covers the run itself.
"""

import json

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers import generation_status as status_mod
from teamarr.consumers.generation import GenerationResult
from teamarr.database import init_db

client = TestClient(app)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


@pytest.fixture(autouse=True)
def _clean_global_status():
    with status_mod._status_lock:
        status_mod._status.reset()
    yield
    with status_mod._status_lock:
        status_mod._status.reset()


def _success_result(**overrides) -> GenerationResult:
    result = GenerationResult()
    result.success = True
    result.run_id = 42
    result.teams_processed = 3
    result.teams_programmes = 30
    result.groups_processed = 2
    result.groups_programmes = 20
    result.programmes_total = 50
    result.duration_seconds = 12.3
    result.file_written = True
    result.file_path = "/data/epg.xml"
    result.file_size = 4096
    for name, value in overrides.items():
        setattr(result, name, value)
    return result


def _sse_frames(raw: str) -> list[str]:
    """Split an SSE body into its raw ``data:``/comment lines, in order."""
    return [line for line in raw.split("\n\n") if line.strip()]


def _sse_payloads(raw: str) -> list[dict]:
    return [
        json.loads(frame[len("data: ") :])
        for frame in _sse_frames(raw)
        if frame.startswith("data: ")
    ]


# ---------------------------------------------------------------------------
# Synchronous API
# ---------------------------------------------------------------------------


def test_sync_success_response_fields(isolated_db, monkeypatch):
    """The response body maps result fields onto these exact names."""
    monkeypatch.setattr(
        "teamarr.api.routes.epg.run_full_generation", lambda **kw: _success_result()
    )

    resp = client.post("/api/v1/epg/generate", json={})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "programmes_count",
        "teams_processed",
        "events_processed",
        "duration_seconds",
        "run_id",
        "match_stats",
    }
    assert body["programmes_count"] == 50
    assert body["teams_processed"] == 3
    # Pinned as-is: "events_processed" carries groups_*programmes*, not
    # groups_processed. Surprising, and a compatibility contract regardless.
    assert body["events_processed"] == 20
    assert body["duration_seconds"] == 12.3
    assert body["run_id"] == 42
    assert set(body["match_stats"]) == {
        "streams_fetched",
        "streams_filtered",
        "streams_eligible",
        "streams_matched",
        "streams_unmatched",
        "streams_cached",
        "match_rate",
    }


def test_sync_run_is_manual(isolated_db, monkeypatch):
    """API-triggered runs pass ``manual=True`` (bypasses the live-event pin, #232)."""
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _success_result()

    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", fake)

    assert client.post("/api/v1/epg/generate", json={}).status_code == 200
    assert seen["manual"] is True
    assert seen["progress_callback"] is not None


def test_sync_success_marks_the_status_tracker_complete(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "teamarr.api.routes.epg.run_full_generation", lambda **kw: _success_result()
    )

    client.post("/api/v1/epg/generate", json={})

    status = client.get("/api/v1/epg/generate/status").json()
    assert status["in_progress"] is False
    assert status["status"] == "complete"
    assert status["result"] == {
        "programmes_count": 50,
        "teams_processed": 3,
        "duration_seconds": 12.3,
    }


def test_sync_unsuccessful_result_is_a_500(isolated_db, monkeypatch):
    """An unsuccessful result becomes HTTP 500 with the error as ``detail``."""
    failed = GenerationResult()
    failed.success = False
    failed.error = "provider exploded"
    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", lambda **kw: failed)

    resp = client.post("/api/v1/epg/generate", json={})

    assert resp.status_code == 500
    assert resp.json()["detail"] == "provider exploded"

    status = client.get("/api/v1/epg/generate/status").json()
    assert status["status"] == "error"
    assert status["error"] == "provider exploded"


def test_sync_duplicate_run_is_a_409(isolated_db, monkeypatch):
    """``start_generation()`` rejecting the run is the 409, before any work."""
    called = []
    monkeypatch.setattr(
        "teamarr.api.routes.epg.run_full_generation",
        lambda **kw: called.append(1) or _success_result(),
    )
    assert status_mod.start_generation() is True

    resp = client.post("/api/v1/epg/generate", json={})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Generation already in progress"
    assert called == []


def test_status_endpoint_serializes_the_tracker(isolated_db):
    resp = client.get("/api/v1/epg/generate/status")
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "in_progress",
        "status",
        "message",
        "percent",
        "phase",
        "current",
        "total",
        "item_name",
        "started_at",
        "completed_at",
        "error",
        "result",
        "cancellation_requested",
    }


def test_cancel_endpoint_status_codes(isolated_db):
    resp = client.post("/api/v1/epg/generate/cancel")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "No generation in progress"

    assert status_mod.start_generation() is True
    resp = client.post("/api/v1/epg/generate/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelling", "message": "Cancellation requested"}


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


def test_sse_emits_initial_progress_and_final_frames(isolated_db, monkeypatch):
    """First frame is the current status, then one per progress call, then final."""

    def fake(db_factory, dispatcharr_client, progress_callback, manual=False):
        progress_callback("teams", 5, "Processing teams...", 0, 0, "")
        progress_callback("groups", 50, "Teams complete", 0, 1, "Loading event groups...")
        return _success_result()

    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", fake)

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        body = "".join(resp.iter_text())

    payloads = _sse_payloads(body)
    assert len(payloads) >= 4

    # Frame 1: the initial status snapshot, emitted before any progress.
    assert payloads[0]["status"] == "starting"
    assert payloads[0]["in_progress"] is True

    phases = [p["phase"] for p in payloads]
    assert "teams" in phases
    assert phases.index("teams") < phases.index("groups")

    # Last frame is the terminal status, repeated after the thread joins.
    assert payloads[-1]["status"] == "complete"
    assert payloads[-1]["in_progress"] is False
    assert payloads[-1]["percent"] == 100
    assert payloads[-1]["result"]["run_id"] == 42
    assert payloads[-1]["result"]["success"] is True
    assert set(payloads[-1]["result"]) == {
        "success",
        "programmes_count",
        "teams_processed",
        "groups_processed",
        "duration_seconds",
        "run_id",
        "match_stats",
    }


def test_sse_every_frame_carries_the_full_status_dict(isolated_db, monkeypatch):
    def fake(db_factory, dispatcharr_client, progress_callback, manual=False):
        progress_callback("saving", 95, "Saving XMLTV...", 0, 0, "")
        return _success_result()

    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", fake)

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        body = "".join(resp.iter_text())

    for payload in _sse_payloads(body):
        assert set(payload) == {
            "in_progress",
            "status",
            "message",
            "percent",
            "phase",
            "current",
            "total",
            "item_name",
            "started_at",
            "completed_at",
            "error",
            "result",
            "cancellation_requested",
        }


def test_sse_frames_are_data_lines_or_heartbeat_comments(isolated_db, monkeypatch):
    """Nothing but ``data: {...}`` frames and ``: heartbeat`` comments."""
    monkeypatch.setattr(
        "teamarr.api.routes.epg.run_full_generation",
        lambda **kw: _success_result(),
    )

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        body = "".join(resp.iter_text())

    for frame in _sse_frames(body):
        assert frame.startswith("data: ") or frame == ": heartbeat", frame


def test_sse_duplicate_run_is_a_single_error_frame(isolated_db, monkeypatch):
    """A second stream while one is running gets one error frame, not a 409."""
    called = []
    monkeypatch.setattr(
        "teamarr.api.routes.epg.run_full_generation",
        lambda **kw: called.append(1) or _success_result(),
    )
    assert status_mod.start_generation() is True

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert _sse_payloads(body) == [{"status": "error", "message": "Generation already in progress"}]
    assert called == []


def test_sse_cancelled_run_does_not_overwrite_the_cancelled_status(isolated_db, monkeypatch):
    """``run_full_generation`` already called ``cancel_generation()``; SSE leaves it."""

    def fake(db_factory, dispatcharr_client, progress_callback, manual=False):
        result = GenerationResult()
        result.success = False
        result.error = "Cancelled by user"
        status_mod.cancel_generation()
        return result

    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", fake)

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        body = "".join(resp.iter_text())

    final = _sse_payloads(body)[-1]
    assert final["status"] == "cancelled"
    assert final["error"] is None


def test_sse_failed_run_reports_the_error(isolated_db, monkeypatch):
    failed = GenerationResult()
    failed.success = False
    failed.error = "provider exploded"
    monkeypatch.setattr("teamarr.api.routes.epg.run_full_generation", lambda **kw: failed)

    with client.stream("GET", "/api/v1/epg/generate/stream") as resp:
        body = "".join(resp.iter_text())

    final = _sse_payloads(body)[-1]
    assert final["status"] == "error"
    assert final["error"] == "provider exploded"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

SCHEDULER_KEYS = {
    "success",
    "error",
    "programmes_generated",
    "teams_processed",
    "teams_programmes",
    "groups_processed",
    "groups_programmes",
    "file_written",
    "file_path",
    "file_size",
    "duration_seconds",
    "m3u_refresh",
    "epg_refresh",
    "epg_association",
    "deletions",
    "reconciliation",
    "cleanup",
    "run_id",
}


def test_scheduler_result_dict_keys(isolated_db, monkeypatch):
    """The cron path flattens the result into exactly these keys."""
    from teamarr.consumers.scheduler import CronScheduler

    monkeypatch.setattr(
        "teamarr.consumers.generation.run_full_generation",
        lambda **kw: _success_result(m3u_refresh={"accounts": 1}),
    )
    monkeypatch.setattr(
        "teamarr.consumers.scheduler.get_dispatcharr_connection", lambda factory: None
    )

    scheduler = CronScheduler(db_factory=lambda: None)
    out = scheduler._task_generate_epg()

    assert set(out) == SCHEDULER_KEYS
    assert out["success"] is True
    assert out["programmes_generated"] == 50
    assert out["teams_processed"] == 3
    assert out["groups_processed"] == 2
    assert out["run_id"] == 42
    assert out["m3u_refresh"] == {"accounts": 1}


def test_scheduled_runs_are_not_manual(isolated_db, monkeypatch):
    """The cron path leaves ``manual`` at its default so the live pin holds (#232)."""
    from teamarr.consumers.scheduler import CronScheduler

    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _success_result()

    monkeypatch.setattr("teamarr.consumers.generation.run_full_generation", fake)
    monkeypatch.setattr(
        "teamarr.consumers.scheduler.get_dispatcharr_connection", lambda factory: None
    )

    CronScheduler(db_factory=lambda: None)._task_generate_epg()

    assert "manual" not in seen


def test_scheduler_reports_a_duplicate_run_without_calling_generation(isolated_db, monkeypatch):
    from teamarr.consumers.scheduler import CronScheduler

    called = []
    monkeypatch.setattr(
        "teamarr.consumers.generation.run_full_generation",
        lambda **kw: called.append(1) or _success_result(),
    )
    assert status_mod.start_generation() is True

    out = CronScheduler(db_factory=lambda: None)._task_generate_epg()

    assert out == {"success": False, "error": "Generation already in progress"}
    assert called == []


def test_scheduler_failure_sets_the_error_status(isolated_db, monkeypatch):
    from teamarr.consumers.scheduler import CronScheduler

    failed = GenerationResult()
    failed.success = False
    failed.error = "provider exploded"
    monkeypatch.setattr("teamarr.consumers.generation.run_full_generation", lambda **kw: failed)
    monkeypatch.setattr(
        "teamarr.consumers.scheduler.get_dispatcharr_connection", lambda factory: None
    )

    out = CronScheduler(db_factory=lambda: None)._task_generate_epg()

    assert out["success"] is False
    assert out["error"] == "provider exploded"
    assert status_mod.get_status()["status"] == "error"
