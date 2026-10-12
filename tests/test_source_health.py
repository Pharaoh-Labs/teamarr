"""Season-aware source-health recommendations (#1044)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from teamarr.database.groups import create_group
from teamarr.database.source_health import set_source_health_decision
from teamarr.services.source_health import (
    get_source_health,
    league_season_active,
    managed_source_idle_days,
)
from teamarr.utilities.tz import to_db_utc


@pytest.fixture
def client(db_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    from teamarr.api.app import app

    return TestClient(app)


def _stamp(value: datetime) -> str:
    return to_db_utc(value)


def _source(conn, *, name="NFL", name_match=True, team=False, epg=False, leagues=None):
    group_id = create_group(conn, name=name, leagues=[], m3u_group_id=123)
    conn.execute(
        """UPDATE event_epg_groups
           SET name_match_enabled = ?, team_streams_enabled = ?, epg_match_enabled = ?,
               subscription_leagues = ?, created_at = ?
           WHERE id = ?""",
        (
            int(name_match),
            int(team),
            int(epg),
            json.dumps(leagues) if leagues is not None else None,
            "2025-01-01 00:00:00",
            group_id,
        ),
    )
    conn.commit()
    return group_id


def _runs(
    conn,
    group_id: int,
    now: datetime,
    *,
    matched=0,
    eligible=20,
    count=5,
    span_days=16,
    error=None,
    provider_failures=0,
    matched_leagues=None,
    matching_types=None,
):
    for index in range(count):
        run_date = now - timedelta(days=span_days * (count - index - 1) / (count - 1))
        summary = {
            "id": group_id,
            "name": "test source",
            "fetched": eligible,
            "eligible": eligible,
            "matched": matched,
            "unmatched": eligible - matched,
            "match_results": matched,
            "matched_leagues": matched_leagues or {},
            "matching_types": matching_types or {"name": True, "team": False, "epg": False},
            "provider_fetch_failures": provider_failures,
            "error": error,
        }
        conn.execute(
            """INSERT INTO processing_runs
                   (run_type, started_at, completed_at, status, extra_metrics)
               VALUES ('full_epg', ?, ?, 'completed', ?)""",
            (_stamp(run_date), _stamp(run_date), json.dumps({"groups": [summary]})),
        )
    conn.commit()


def _record_league_activity(conn, now: datetime, league: str) -> None:
    """A separate source proves the league has supplied events recently."""
    summary = {
        "id": 9999,
        "name": "independent schedule evidence",
        "fetched": 1,
        "eligible": 1,
        "matched": 1,
        "unmatched": 0,
        "matched_leagues": {league: 1},
        "matching_types": {"name": True, "team": False, "epg": False},
        "provider_fetch_failures": 0,
    }
    conn.execute(
        """INSERT INTO processing_runs
               (run_type, started_at, completed_at, status, extra_metrics)
           VALUES ('full_epg', ?, ?, 'completed', ?)""",
        (_stamp(now), _stamp(now), json.dumps({"groups": [summary]})),
    )
    conn.commit()


def _recommendations(conn, now: datetime, *, include_hidden=False):
    return get_source_health(conn, now=now, include_hidden=include_hidden)


def test_nfl_is_active_in_regular_season_and_quiet_in_spring():
    assert league_season_active("nfl", date(2026, 10, 12)) is True
    assert league_season_active("nfl", date(2026, 5, 12)) is False


def test_nhl_and_mlb_calendar_windows_include_playoffs_and_spring_training():
    assert league_season_active("nhl", date(2026, 6, 20)) is True
    assert league_season_active("nhl", date(2026, 7, 20)) is False
    assert league_season_active("mlb", date(2026, 3, 15)) is True
    assert league_season_active("mlb", date(2026, 12, 15)) is False


def test_unknown_league_seasonality_is_not_guessed():
    assert league_season_active("some.custom.league", date(2026, 7, 1)) is None


def test_managed_retirement_clock_pauses_offseason_and_resets_for_new_season():
    last_match = datetime(2026, 2, 15, tzinfo=UTC)
    created = datetime(2025, 10, 1, tzinfo=UTC)
    offseason = datetime(2026, 7, 15, tzinfo=UTC)
    in_season = datetime(2026, 10, 12, tzinfo=UTC)

    assert managed_source_idle_days(last_match, created, ["nhl"], offseason, set()) is None
    # NHL's broad season starts Sep 1; the 21-day opening grace makes Sep 22
    # the start of meaningful idle time (20 days by Oct 12).
    assert managed_source_idle_days(last_match, created, ["nhl"], in_season, {"nhl"}) == 20
    assert managed_source_idle_days(last_match, created, ["unknown"], in_season, {"nhl"}) is None


def test_nfl_offseason_quiet_source_is_not_recommended(db_conn):
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 2, 9, tzinfo=UTC)), '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now)

    assert _recommendations(db_conn, now)["recommendations"] == []


def test_nfl_quiet_source_is_suggested_after_repeated_in_season_runs(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 2, 9, tzinfo=UTC)), '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now)
    _record_league_activity(db_conn, now, "nfl")

    recommendation = _recommendations(db_conn, now)["recommendations"][0]
    assert recommendation["kind"] == "quiet"
    assert recommendation["leagues"] == ["nfl"]
    assert recommendation["sample_runs"] == 5


def test_recent_matched_event_overrides_calendar_offseason(db_conn):
    now = datetime(2026, 3, 10, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, last_matched_leagues = ? WHERE id = ?",
        (_stamp(now - timedelta(days=4)), '["nfl"]', group_id),
    )
    _runs(
        db_conn,
        group_id,
        now,
        matched=1,
        matched_leagues={"nfl": 1},
    )

    recommendation = _recommendations(db_conn, now)["recommendations"][0]
    assert recommendation["kind"] == "low_coverage"


def test_mixed_source_is_active_if_one_league_is_in_season(db_conn):
    now = datetime(2026, 12, 15, 12, tzinfo=UTC)
    group_id = _source(db_conn, name="NFL + MLB", leagues=["nfl", "mlb"])
    _runs(db_conn, group_id, now)
    _record_league_activity(db_conn, now, "nfl")

    result = _recommendations(db_conn, now)["recommendations"]
    assert len(result) == 1
    assert result[0]["kind"] == "quiet"
    assert result[0]["leagues"] == ["nfl"]


def test_generic_source_uses_inherited_global_league_scope(db_conn):
    now = datetime(2026, 12, 15, 12, tzinfo=UTC)
    group_id = _source(db_conn, name="ESPN+")
    db_conn.execute(
        "UPDATE sports_subscription SET leagues = ? WHERE id = 1",
        (json.dumps(["nfl", "mlb"]),),
    )
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, "
        "last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 10, 1, tzinfo=UTC)), '["mlb"]', group_id),
    )
    _runs(db_conn, group_id, now)
    _record_league_activity(db_conn, now, "nfl")

    recommendations = _recommendations(db_conn, now)["recommendations"]
    assert recommendations[0]["group_id"] == group_id
    assert recommendations[0]["kind"] == "quiet"
    assert recommendations[0]["leagues"] == ["nfl"]


def test_low_coverage_requires_name_matching_and_minimum_sample(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    name_group = _source(db_conn, name="NFL name source")
    team_group = _source(db_conn, name="NFL team source", name_match=False, team=True)
    small_group = _source(db_conn, name="NFL small source")
    for group_id in (name_group, team_group, small_group):
        db_conn.execute(
            "UPDATE event_epg_groups SET last_matched_at = ?, "
            "last_matched_leagues = ? WHERE id = ?",
            (_stamp(now - timedelta(days=20)), '["nfl"]', group_id),
        )
    _runs(db_conn, name_group, now, eligible=5, matched=0)
    _runs(db_conn, team_group, now, eligible=5, matched=0)
    _runs(db_conn, small_group, now, eligible=3, matched=0)
    _record_league_activity(db_conn, now, "nfl")

    recommendations = _recommendations(db_conn, now)["recommendations"]
    assert [item["group_id"] for item in recommendations] == [name_group]
    assert recommendations[0]["kind"] == "low_coverage"
    assert recommendations[0]["coverage"] == 0
    assert recommendations[0]["eligible_observations"] == 25


def test_empty_group_runs_do_not_count_as_health_evidence(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, "
        "last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 2, 9, tzinfo=UTC)), '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now, eligible=0)
    _record_league_activity(db_conn, now, "nfl")

    assert _recommendations(db_conn, now)["recommendations"] == []


def test_failed_group_runs_do_not_count_as_health_evidence(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 2, 9, tzinfo=UTC)), '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now, error="provider unavailable")

    assert _recommendations(db_conn, now)["recommendations"] == []


def test_provider_fetch_failures_do_not_count_as_health_evidence(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, "
        "last_matched_leagues = ? WHERE id = ?",
        (_stamp(datetime(2026, 2, 9, tzinfo=UTC)), '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now, provider_failures=1)

    assert _recommendations(db_conn, now)["recommendations"] == []


def test_keep_hides_until_match_watermark_changes(db_conn):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    group_id = _source(db_conn)
    last_match = _stamp(datetime(2026, 2, 9, tzinfo=UTC))
    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ?, last_matched_leagues = ? WHERE id = ?",
        (last_match, '["nfl"]', group_id),
    )
    _runs(db_conn, group_id, now)
    _record_league_activity(db_conn, now, "nfl")
    set_source_health_decision(
        db_conn, group_id, "keep", last_matched_at=last_match, now=now
    )

    hidden = _recommendations(db_conn, now)
    assert hidden["recommendations"] == []
    assert hidden["hidden_count"] == 1
    assert _recommendations(db_conn, now, include_hidden=True)["recommendations"][0][
        "decision"
    ] == "keep"

    db_conn.execute(
        "UPDATE event_epg_groups SET last_matched_at = ? WHERE id = ?",
        (_stamp(datetime(2026, 8, 1, tzinfo=UTC)), group_id),
    )
    db_conn.commit()
    assert _recommendations(db_conn, now)["recommendations"]


def test_health_api_exposes_recommendations_and_decisions(client, db_conn):
    group_id = _source(db_conn)

    response = client.get("/api/v1/groups/health/recommendations")
    assert response.status_code == 200
    assert response.json()["recommendations"] == []

    kept = client.post(f"/api/v1/groups/{group_id}/health/keep")
    assert kept.status_code == 200
    assert kept.json() == {"group_id": group_id, "decision": "keep"}
    assert db_conn.execute(
        "SELECT decision FROM source_health_decisions WHERE group_id = ?", (group_id,)
    ).fetchone()[0] == "keep"

    snoozed = client.post(f"/api/v1/groups/{group_id}/health/snooze")
    assert snoozed.status_code == 200
    assert db_conn.execute(
        "SELECT decision, snoozed_until FROM source_health_decisions WHERE group_id = ?",
        (group_id,),
    ).fetchone()["decision"] == "snooze"

    restored = client.delete(f"/api/v1/groups/{group_id}/health/decision")
    assert restored.status_code == 200
    assert restored.json() == {"group_id": group_id, "restored": True}


def test_health_api_rejects_system_channel_sources(client, db_conn):
    group_id = _source(db_conn)
    db_conn.execute("UPDATE event_epg_groups SET is_channel_source = 1 WHERE id = ?", (group_id,))
    db_conn.commit()

    response = client.post(f"/api/v1/groups/{group_id}/health/keep")
    assert response.status_code == 400
