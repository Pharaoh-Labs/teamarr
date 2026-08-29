"""Support exports are safe, structured, and useful without a live integration."""
# ruff: noqa: E501

import json
import zipfile
from io import BytesIO

from teamarr.database.connection import get_connection
from teamarr.services.support_bundle import SupportBundleService


def test_bundle_contains_contract_and_redacts_source_data(db_path, tmp_path):
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE settings SET dispatcharr_enabled = 1, dispatcharr_url = ?",
            ("https://user:secret@example.test/api?token=abc",),
        )
        conn.execute(
            "INSERT INTO teams (provider_team_id, primary_league, sport, team_name, channel_id, active) VALUES (?, ?, ?, ?, ?, 1)",
            ("1", "nba", "basketball", "Unassigned Team", "team-1"),
        )
        conn.execute(
            "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) VALUES (?, ?, ?, ?)",
            ("event-1", "espn", "teamarr.event-1", "Example Channel"),
        )
        channel_id = conn.execute("SELECT id FROM managed_channels").fetchone()[0]
        conn.execute(
            "INSERT INTO managed_channel_streams (managed_channel_id, dispatcharr_stream_id, stream_name, m3u_account_name) VALUES (?, ?, ?, ?)",
            (channel_id, 17, "Example Stream", "Private Account"),
        )
        conn.commit()

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "teamarr.log").write_text(
        "stream https://stream.example/live Private Account sb_publishable_abcdef\n"
    )
    bundle = SupportBundleService(db_path, logs).create()

    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        assert archive.namelist() == [
            "AGENTS.md",
            "support-report.json",
            "recent-runs.json",
            "recent-run-stream-details.json",
            "logs/teamarr-recent.log",
        ]
        contents = "\n".join(archive.read(name).decode() for name in archive.namelist())
        report = json.loads(archive.read("support-report.json"))

    assert list(report)[:3] == ["schema_version", "summary", "signals"]
    assert "teams_without_template" in {signal["code"] for signal in report["signals"]}
    assert "Private Account" not in contents
    assert "https://stream.example/live" not in contents
    assert "sb_publishable_abcdef" not in contents
    assert "secret@example.test" not in contents


def test_bundle_signals_media_server_failing(db_path, tmp_path):
    from teamarr.database.stats import create_run, save_run

    with get_connection(db_path) as conn:
        for _ in range(3):
            run = create_run(conn, run_type="full_epg")
            run.extra_metrics["media_servers"] = [
                {"kind": "emby", "server": "Emby", "success": False, "duration": 0.02,
                 "error": "connection refused"}
            ]
            run.complete()
            save_run(conn, run)

    logs = tmp_path / "logs"
    logs.mkdir()
    bundle = SupportBundleService(db_path, logs).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        report = json.loads(archive.read("support-report.json"))
        guide = archive.read("AGENTS.md").decode()

    [signal] = [s for s in report["signals"] if s["code"] == "media_server_refresh_failing"]
    assert signal["severity"] == "warning"
    assert signal["evidence"]["servers"][0]["consecutive_failures"] == 3
    assert "media_server_refresh_failing" in guide
