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
                {
                    "kind": "emby",
                    "server": "Emby",
                    "success": False,
                    "duration": 0.02,
                    "error": "connection refused",
                }
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


def _run_with_groups(conn, groups):
    from teamarr.database.stats import create_run, save_run

    run = create_run(conn, run_type="full_epg")
    run.extra_metrics["groups"] = groups
    run.complete()
    save_run(conn, run)


def test_bundle_signals_source_matching_zero_and_degraded(db_path, tmp_path):
    """Matching outcomes reach the signal layer (#657).

    A bundle from an install whose sources matched nothing used to lead with
    "No automatic signals were found" — the first line a triager reads.
    """
    with get_connection(db_path) as conn:
        _run_with_groups(
            conn,
            [
                {"id": 164, "name": "NCAAF PACKAGE [1080p]", "matched": 0, "unmatched": 30},
                {"id": 375, "name": "AU | Bar TV", "matched": 0, "unmatched": 200},
                {"id": 9, "name": "NCAAF Events", "matched": 10, "unmatched": 25},
                {"id": 2, "name": "Healthy", "matched": 40, "unmatched": 5},
            ],
        )

    logs = tmp_path / "logs"
    logs.mkdir()
    bundle = SupportBundleService(db_path, logs).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        report = json.loads(archive.read("support-report.json"))
        guide = archive.read("AGENTS.md").decode()

    [zero] = [s for s in report["signals"] if s["code"] == "source_matching_zero"]
    assert zero["severity"] == "warning"
    assert zero["evidence"]["total"] == 2
    # Ranked by stream count, so a truncated list keeps the biggest offenders.
    assert [s["id"] for s in zero["evidence"]["sources"]] == [375, 164]

    [degraded] = [s for s in report["signals"] if s["code"] == "source_matching_degraded"]
    assert degraded["severity"] == "info"
    assert [s["id"] for s in degraded["evidence"]["sources"]] == [9]

    assert "source_matching_zero" in guide


def test_off_season_source_with_no_matchable_streams_is_silent(db_path, tmp_path):
    """`fetched` is pre-filter; the denominator is matched + unmatched.

    "USA | NFL Teams Backup" fetches 34 streams in August and offers none of
    them to the matcher. Reporting that at 0% would fire on every source that
    is merely out of season.
    """
    with get_connection(db_path) as conn:
        _run_with_groups(
            conn,
            [
                {
                    "id": 11,
                    "name": "NFL Teams Backup",
                    "fetched": 34,
                    "matched": 0,
                    "unmatched": 0,
                },
                # Too few streams to mean anything: 72 of 131 zero-match sources
                # on the reference install had fewer than five.
                {"id": 30, "name": "NCAA Baseball", "matched": 0, "unmatched": 1},
            ],
        )

    logs = tmp_path / "logs"
    logs.mkdir()
    bundle = SupportBundleService(db_path, logs).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        report = json.loads(archive.read("support-report.json"))

    codes = {s["code"] for s in report["signals"]}
    assert "source_matching_zero" not in codes
    assert "source_matching_degraded" not in codes


def test_matching_signals_absent_when_run_predates_group_breakdown(db_path, tmp_path):
    """#645 moved the per-source breakdown onto the parent run. A run without
    it (in progress, or written before v90) yields no opinion rather than a
    guess from the retired event_group rows."""
    from teamarr.database.stats import create_run, save_run

    with get_connection(db_path) as conn:
        run = create_run(conn, run_type="full_epg")
        run.complete()
        save_run(conn, run)

    logs = tmp_path / "logs"
    logs.mkdir()
    bundle = SupportBundleService(db_path, logs).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        report = json.loads(archive.read("support-report.json"))

    codes = {s["code"] for s in report["signals"]}
    assert "source_matching_zero" not in codes


def test_bundle_redacts_credentials_nested_in_json_settings(db_path, tmp_path):
    """JSON-typed settings columns are parsed and redacted at every depth (#686).

    ``emby_servers`` / ``jellyfin_servers`` are stored as JSON text. Key-name
    redaction only ran on dict keys, so the ``api_key`` and ``password`` inside
    the text survived while the top-level ``emby_api_key`` was masked.
    """
    servers = json.dumps(
        [
            {
                "name": "Living Room",
                "url": "http://emby.local:8096",
                "username": "media",
                "password": "hunter2-emby",
                "api_key": "emby-key-0123456789",
            }
        ]
    )
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE settings SET emby_servers = ?, jellyfin_servers = ?",
            (servers, servers.replace("emby", "jelly")),
        )
        conn.commit()

    logs = tmp_path / "logs"
    logs.mkdir()
    bundle = SupportBundleService(db_path, logs).create()
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        contents = "\n".join(archive.read(name).decode() for name in archive.namelist())
        report = json.loads(archive.read("support-report.json"))

    for leaked in ("hunter2-emby", "emby-key-0123456789", "hunter2-jelly", "jelly-key-0123456789"):
        assert leaked not in contents
    [emby] = report["configuration"]["settings"]["emby_servers"]
    assert emby["name"] == "Living Room"
    assert emby["password"] == "[REDACTED]"
    assert emby["api_key"] == "[REDACTED]"
    assert "emby.local" not in emby["url"]
