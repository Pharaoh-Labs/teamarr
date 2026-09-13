"""Tests for user-defined broadcaster mappings DB, API routes, and matching integration."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.database import get_db, init_db
from teamarr.database.broadcaster_mappings import (
    create_broadcaster_mapping,
    delete_broadcaster_mapping,
    get_broadcaster_mapping,
    list_broadcaster_mappings,
    match_user_broadcaster,
    update_broadcaster_mapping,
)
from tests.fakes import FakeTeam, make_event


def test_broadcaster_mapping_db_crud():
    """Test full database CRUD operations for broadcaster mappings."""
    init_db()
    with get_db() as conn:
        # 1. Create
        mapping = create_broadcaster_mapping(
            conn=conn,
            name="MASN Orioles",
            pattern=r"(?i)\bMASN\b",
            pattern_type="regex",
            team_id="BAL",
            team_name="Baltimore Orioles",
            league="mlb",
            is_active=True,
        )
        assert mapping.id is not None
        assert mapping.name == "MASN Orioles"
        assert mapping.team_id == "BAL"

        # 2. Get
        fetched = get_broadcaster_mapping(conn, mapping.id)
        assert fetched is not None
        assert fetched.pattern == r"(?i)\bMASN\b"

        # 3. List
        mappings = list_broadcaster_mappings(conn, league="mlb")
        assert any(m.id == mapping.id for m in mappings)

        # 4. Update
        updated = update_broadcaster_mapping(
            conn, mapping.id, name="MASN Orioles HD", is_active=False
        )
        assert updated is not None
        assert updated.name == "MASN Orioles HD"
        assert updated.is_active is False

        # 5. Delete
        success = delete_broadcaster_mapping(conn, mapping.id)
        assert success is True
        assert get_broadcaster_mapping(conn, mapping.id) is None


def test_match_user_broadcaster_helper():
    """Test match_user_broadcaster helper across regex, exact, and tvg_id patterns."""
    init_db()
    with get_db() as conn:
        m1 = create_broadcaster_mapping(
            conn,
            name="MASN",
            pattern=r"(?i)\bMASN\b",
            pattern_type="regex",
            team_id="BAL",
            league="mlb",
        )
        m2 = create_broadcaster_mapping(
            conn,
            name="NESN 4K",
            pattern="US: NESN 4K",
            pattern_type="exact",
            team_id="BOS",
            league="mlb",
        )
        m3 = create_broadcaster_mapping(
            conn,
            name="SNY TVG",
            pattern="SNY.us",
            pattern_type="tvg_id",
            team_id="NYM",
            league="mlb",
        )

        mappings = [m1, m2, m3]

        # Regex match
        assert match_user_broadcaster("US: MASN HD (Baltimore)", "mlb", mappings) == "BAL"

        # Exact match
        assert match_user_broadcaster("US: NESN 4K", "mlb", mappings) == "BOS"
        assert match_user_broadcaster("US: NESN 4K 60FPS", "mlb", mappings) is None

        # tvg_id match
        assert match_user_broadcaster("Random Name", "mlb", mappings, tvg_id="SNY.us") == "NYM"

        # League filter mismatch
        assert match_user_broadcaster("US: MASN HD", "nfl", mappings) is None

        # Clean up
        for m in mappings:
            delete_broadcaster_mapping(conn, m.id)


def test_broadcaster_mappings_api_routes():
    """Test FastAPI endpoints for broadcaster mappings."""
    app = create_app()
    client = TestClient(app)

    # 1. Get Catalog
    catalog_res = client.get("/api/v1/broadcasters/catalog?league=mlb")
    assert catalog_res.status_code == 200
    catalog = catalog_res.json()
    assert len(catalog) > 0
    assert any(e["team_abbreviation"] == "NYY" for e in catalog)

    # 2. Create Custom Mapping
    create_res = client.post(
        "/api/v1/broadcasters/",
        json={
            "name": "MASN Orioles Test",
            "pattern": r"(?i)\bMASN\b",
            "pattern_type": "regex",
            "team_id": "BAL",
            "team_name": "Baltimore Orioles",
            "league": "mlb",
            "is_active": True,
        },
    )
    assert create_res.status_code == 201
    created = create_res.json()
    mapping_id = created["id"]
    assert created["name"] == "MASN Orioles Test"

    # 3. List
    list_res = client.get("/api/v1/broadcasters/?league=mlb")
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(i["id"] == mapping_id for i in items)

    # 4. Get by ID
    get_res = client.get(f"/api/v1/broadcasters/{mapping_id}")
    assert get_res.status_code == 200
    assert get_res.json()["team_id"] == "BAL"

    # 5. Update
    update_res = client.put(
        f"/api/v1/broadcasters/{mapping_id}",
        json={"name": "MASN Orioles Updated", "is_active": False},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "MASN Orioles Updated"
    assert update_res.json()["is_active"] is False

    # 6. Delete
    del_res = client.delete(f"/api/v1/broadcasters/{mapping_id}")
    assert del_res.status_code == 204

    # 7. Verify 404 after delete
    get_after_del = client.get(f"/api/v1/broadcasters/{mapping_id}")
    assert get_after_del.status_code == 404


def test_user_mapping_resolves_ambiguous_masn_in_matching():
    """User-defined mapping disambiguates MASN to Orioles Home feed."""
    matcher = StreamMatching()
    orioles = FakeTeam(id="110", name="Baltimore Orioles", abbreviation="BAL")
    nationals = FakeTeam(id="120", name="Washington Nationals", abbreviation="WSH")

    event = make_event(
        id="1005",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 6, 15, 23, 5, tzinfo=UTC),
        home_team=orioles,
        away_team=nationals,
    )

    matched_streams = [
        {
            "stream": {"id": 10, "name": "US: MASN HD", "tvg_id": "MASN.us"},
            "event": event,
            "feed_hint": None,
        }
    ]

    # Without user mapping: stays None (zero guessing)
    resolved_no_user = matcher._resolve_feed_teams(
        matched_streams,
        detect_team_names=False,
        separation_enabled=True,
        user_broadcaster_mappings=[],
    )
    assert resolved_no_user[0]["stream_feed_team"] is None

    # With user mapping (MASN -> BAL):
    init_db()
    with get_db() as conn:
        mapping = create_broadcaster_mapping(
            conn,
            name="MASN Orioles",
            pattern=r"(?i)\bMASN\b",
            pattern_type="regex",
            team_id="BAL",
            league="mlb",
        )
        resolved_with_user = matcher._resolve_feed_teams(
            matched_streams,
            detect_team_names=False,
            separation_enabled=True,
            user_broadcaster_mappings=[mapping],
        )
        assert resolved_with_user[0]["stream_feed_team"] == orioles
        assert resolved_with_user[0]["feed_team"] == orioles
        delete_broadcaster_mapping(conn, mapping.id)
