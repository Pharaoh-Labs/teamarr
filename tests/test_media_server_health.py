"""Media-server refresh outcomes are persisted and repeated failures surfaced (#649).

A down/moved media server never fails a generation (by design), which is why
prod's Emby + Channels DVR pointed at a decommissioned host for three weeks
unnoticed. Outcomes now live on the run row; the health helper turns them
into a per-server "failing" flag after consecutive misses.
"""

from teamarr.consumers.generation import _media_server_outcome
from teamarr.database.stats import (
    create_run,
    get_current_stats,
    get_media_server_health,
    media_server_health,
    save_run,
)


def _run(*outcomes, completed="2026-08-29T13:00:00+00:00"):
    return {"completed_at": completed, "extra_metrics": {"media_servers": list(outcomes)}}


def _o(server, ok, kind="emby", error=None):
    return {"kind": kind, "server": server, "success": ok, "duration": 0.0, "error": error}


# ---------------------------------------------------------------------------
# _media_server_outcome — flattening one server's refresh result
# ---------------------------------------------------------------------------


def test_emby_outcome_flattens_guide_result():
    o = _media_server_outcome("emby", "Emby", {"guide": {"success": False, "error": "refused"}})
    assert o == {
        "kind": "emby", "server": "Emby", "success": False, "duration": 0.0, "error": "refused",
    }


def test_channelsdvr_outcome_needs_both_steps():
    ok = {"m3u": {"success": True, "duration": 1.5}, "epg": {"success": True, "duration": 2.0}}
    assert _media_server_outcome("channelsdvr", "C", ok)["success"] is True
    assert _media_server_outcome("channelsdvr", "C", ok)["duration"] == 3.5
    half = {"m3u": {"success": True}, "epg": {"success": False, "message": "timed out"}}
    o = _media_server_outcome("channelsdvr", "C", half)
    assert o["success"] is False and o["error"] == "timed out"


# ---------------------------------------------------------------------------
# media_server_health — consecutive failures from newest run backwards
# ---------------------------------------------------------------------------


def test_consecutive_failures_counted_from_newest():
    runs = [  # newest first
        _run(_o("Emby", False, error="refused"), completed="t3"),
        _run(_o("Emby", False, error="refused"), completed="t2"),
        _run(_o("Emby", False, error="refused"), completed="t1"),
        _run(_o("Emby", True), completed="t0"),
    ]
    [h] = media_server_health(runs)
    assert h["consecutive_failures"] == 3
    assert h["failing"] is True
    assert h["last_error"] == "refused"
    assert h["last_success_at"] == "t0"


def test_a_success_breaks_the_streak():
    runs = [_run(_o("Emby", False)), _run(_o("Emby", True)), _run(_o("Emby", False))]
    [h] = media_server_health(runs)
    assert h["consecutive_failures"] == 1
    assert h["failing"] is False


def test_threshold_and_per_server_independence():
    runs = [_run(_o("A", False), _o("B", True, kind="channelsdvr"))] * 3
    by = {h["server"]: h for h in media_server_health(runs)}
    assert by["A"]["failing"] is True and by["B"]["failing"] is False
    assert media_server_health(runs, threshold=4)[0]["failing"] is False


def test_runs_without_outcomes_are_ignored():
    assert media_server_health([{"extra_metrics": {}}, {}]) == []


# ---------------------------------------------------------------------------
# Persistence round-trip through processing_runs
# ---------------------------------------------------------------------------


def test_health_reads_persisted_run_rows(db_conn):
    for hour in range(3):
        run = create_run(db_conn, run_type="full_epg")
        run.extra_metrics["media_servers"] = [_o("Emby", False, error="connection refused")]
        save_run(db_conn, run)
        # get_recent_runs collapses full runs that started in the same minute
        # (parallel-process guard); real runs are an hour apart.
        db_conn.execute(
            "UPDATE processing_runs SET started_at = ? WHERE id = ?",
            (f"2026-08-29 {10 + hour:02d}:00:00", run.id),
        )
    db_conn.commit()

    [h] = get_media_server_health(db_conn)
    assert h["failing"] is True and h["last_error"] == "connection refused"
    assert get_current_stats(db_conn)["media_server_health"][0]["server"] == "Emby"
