"""Tests for custom-league policy: premium gate (eqz.1) + sport guardrails (eqz.8).

These exercise the single source of truth in ``services/custom_leagues.py`` that
the write path (eqz.2) and the test-fetch validator (eqz.3) will both enforce.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teamarr.services.custom_leagues import (
    ALLOWED_EVENT_TYPES,
    FUNCTIONAL_SPORTS,
    CustomLeagueGateError,
    CustomLeagueNotFoundError,
    CustomLeagueProtectedError,
    CustomLeagueValidationError,
    create_custom_league,
    custom_leagues_enabled,
    default_event_type,
    delete_custom_league,
    is_supported_sport,
    list_custom_leagues_with_state,
    require_custom_leagues_enabled,
    run_custom_league_test_fetch,
    supported_custom_league_sports,
    tsdb_sport_to_teamarr,
    update_custom_league,
    validate_custom_league_sport,
    validate_event_type,
    validate_tsdb_sport_matches,
)

SCHEMA = Path(__file__).resolve().parents[1] / "teamarr" / "database" / "schema.sql"


def _db() -> sqlite3.Connection:
    """Fresh in-memory DB seeded from schema.sql (no premium key by default)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _set_key(conn: sqlite3.Connection, key: str | None) -> None:
    conn.execute("UPDATE settings SET tsdb_api_key = ? WHERE id = 1", (key,))


# ---------------------------------------------------------------------------
# Premium gate (eqz.1)
# ---------------------------------------------------------------------------


def test_gate_locked_without_key():
    conn = _db()
    assert custom_leagues_enabled(conn) is False
    with pytest.raises(CustomLeagueGateError):
        require_custom_leagues_enabled(conn)


def test_gate_unlocked_with_key():
    conn = _db()
    _set_key(conn, "premium-abc123")
    assert custom_leagues_enabled(conn) is True
    require_custom_leagues_enabled(conn)  # does not raise


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_gate_treats_blank_key_as_locked(blank):
    conn = _db()
    _set_key(conn, blank)
    assert custom_leagues_enabled(conn) is False


# ---------------------------------------------------------------------------
# Sport allowlist (eqz.8)
# ---------------------------------------------------------------------------


def test_functional_sports_excludes_placeholder_sports():
    # Roadmap placeholders with no matcher must never be selectable.
    for placeholder in ("tennis", "golf", "racing", "wrestling"):
        assert placeholder not in FUNCTIONAL_SPORTS
        assert is_supported_sport(placeholder) is False


def test_functional_sports_includes_matcher_backed_sports():
    for sport in ("soccer", "cricket", "boxing", "mma", "hockey", "rugby"):
        assert is_supported_sport(sport) is True


def test_supported_sports_intersects_table_with_functional_set():
    conn = _db()
    sports = supported_custom_league_sports(conn)
    codes = {s["sport_code"] for s in sports}
    assert codes == set(FUNCTIONAL_SPORTS)
    # Placeholder sports are in the table but excluded from the picker.
    assert "tennis" not in codes
    # Display names come through for the UI.
    assert all(s["display_name"] for s in sports)


def test_validate_sport_rejects_unsupported():
    validate_custom_league_sport("soccer")  # ok
    with pytest.raises(CustomLeagueValidationError):
        validate_custom_league_sport("tennis")
    with pytest.raises(CustomLeagueValidationError):
        validate_custom_league_sport("underwater-hockey")


# ---------------------------------------------------------------------------
# event_type guardrail (eqz.8)
# ---------------------------------------------------------------------------


def test_default_event_type_by_sport():
    assert default_event_type("boxing") == "event_card"
    assert default_event_type("mma") == "event_card"
    assert default_event_type("soccer") == "team_vs_team"
    assert default_event_type("hockey") == "team_vs_team"


def test_validate_event_type():
    for et in ALLOWED_EVENT_TYPES:
        validate_event_type(et)
    with pytest.raises(CustomLeagueValidationError):
        validate_event_type("event")  # schema default but not matcher-supported
    with pytest.raises(CustomLeagueValidationError):
        validate_event_type("bogus")


# ---------------------------------------------------------------------------
# TSDB sport cross-check (eqz.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "str_sport,expected",
    [
        ("Soccer", "soccer"),
        ("soccer", "soccer"),
        ("  Cricket  ", "cricket"),
        ("Fighting", "mma"),
        ("Ice Hockey", "hockey"),
        ("American Football", "football"),
        ("Australian Football", "australian-football"),
        ("Curling", None),
        ("", None),
        (None, None),
    ],
)
def test_tsdb_sport_mapping(str_sport, expected):
    assert tsdb_sport_to_teamarr(str_sport) == expected


def test_cross_check_accepts_match():
    validate_tsdb_sport_matches("Soccer", "soccer")  # does not raise


def test_cross_check_rejects_mismatch():
    # User picked soccer but TSDB says it's cricket — the mislabel guardrail.
    with pytest.raises(CustomLeagueValidationError) as exc:
        validate_tsdb_sport_matches("Cricket", "soccer")
    assert "mismatch" in str(exc.value).lower()


def test_cross_check_rejects_unmapped_sport():
    with pytest.raises(CustomLeagueValidationError):
        validate_tsdb_sport_matches("Curling", "soccer")


# ---------------------------------------------------------------------------
# Capability endpoint (eqz.1) — structural smoke test against the live app
# ---------------------------------------------------------------------------


def test_capability_endpoint_shape():
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    resp = TestClient(app).get("/api/v1/leagues/custom/capability")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["enabled"], bool)
    codes = {s["sport_code"] for s in body["supported_sports"]}
    assert codes == set(FUNCTIONAL_SPORTS)
    assert "tennis" not in codes  # placeholder sport never offered


# ---------------------------------------------------------------------------
# Write path (eqz.2)
# ---------------------------------------------------------------------------

_VALID = dict(
    league_code="swe.1",
    provider_league_id="4379",
    provider_league_name="Swedish Allsvenskan",
    display_name="Allsvenskan",
    sport="soccer",
)


def _premium_db() -> sqlite3.Connection:
    conn = _db()
    _set_key(conn, "premium-abc123")
    return conn


def test_create_requires_premium_key():
    conn = _db()  # no key
    with pytest.raises(CustomLeagueGateError):
        create_custom_league(conn, **_VALID)


def test_create_rejects_non_tsdb_provider():
    conn = _premium_db()
    with pytest.raises(CustomLeagueValidationError):
        create_custom_league(conn, provider="espn", **_VALID)


def test_create_persists_custom_row(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)  # create now live-validates before insert
    row = create_custom_league(conn, **_VALID)
    assert row["is_custom"] == 1
    assert row["provider"] == "tsdb"
    assert row["enabled"] == 1
    # event_type defaulted from sport (soccer → team_vs_team)
    assert row["event_type"] == "team_vs_team"
    # Persisted and readable back.
    stored = conn.execute(
        "SELECT provider_league_name, is_custom FROM leagues WHERE league_code = 'swe.1'"
    ).fetchone()
    assert stored["provider_league_name"] == "Swedish Allsvenskan"
    assert stored["is_custom"] == 1


# ---------------------------------------------------------------------------
# Auto-subscribe + subscription-state warning (#240 UX guard)
# ---------------------------------------------------------------------------


def _sub_leagues(conn):
    from teamarr.database.subscription import get_subscription

    return get_subscription(conn).leagues


def test_create_auto_subscribes_league(monkeypatch):
    """A new custom league lands in the global subscription so its games match.

    Group match/inclusion leagues resolve from sports_subscription; without this,
    a freshly-created league silently produces no events (GH #240).
    """
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    assert "swe.1" in _sub_leagues(conn)


def test_auto_subscribe_preserves_existing_and_no_duplicates(monkeypatch):
    from teamarr.database.subscription import update_subscription

    conn = _premium_db()
    update_subscription(conn, leagues=["eng.1"])
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    # Existing subscription preserved, new code appended exactly once.
    assert _sub_leagues(conn) == ["eng.1", "swe.1"]


def test_list_with_state_flags_subscribed(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)

    rows = list_custom_leagues_with_state(conn)
    assert len(rows) == 1
    assert rows[0]["league_code"] == "swe.1"
    assert rows[0]["subscribed"] is True


def test_list_with_state_flags_unsubscribed_after_user_unsubscribes(monkeypatch):
    """If the user later unchecks the league, the warning flag flips to False."""
    from teamarr.database.subscription import update_subscription

    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    update_subscription(conn, leagues=[])  # user unsubscribes everything

    rows = list_custom_leagues_with_state(conn)
    assert rows[0]["subscribed"] is False


def test_create_defaults_event_card_for_combat_sport(monkeypatch):
    conn = _premium_db()

    class _Boxing(_FakeTSDBClient):
        league = {"strLeague": "Some Boxing Series", "strSport": "Boxing"}

    _patch_client(monkeypatch, _Boxing)
    row = create_custom_league(
        conn,
        league_code="custom.box",
        provider_league_id="4445",
        provider_league_name="Some Boxing Series",
        display_name="Boxing Series",
        sport="boxing",
    )
    assert row["event_type"] == "event_card"


def test_create_rejects_collision_with_builtin():
    conn = _premium_db()
    # 'nfl' is a built-in seeded by schema.sql.
    with pytest.raises(CustomLeagueValidationError) as exc:
        create_custom_league(
            conn,
            league_code="nfl",
            provider_league_id="4391",
            provider_league_name="NFL",
            display_name="My NFL",
            sport="football",
        )
    assert "already exists" in str(exc.value).lower()
    # The built-in is untouched (still ESPN, still not custom).
    builtin = conn.execute(
        "SELECT provider, is_custom FROM leagues WHERE league_code = 'nfl'"
    ).fetchone()
    assert builtin["provider"] == "espn"
    assert builtin["is_custom"] == 0


def test_create_rejects_unsupported_sport():
    conn = _premium_db()
    with pytest.raises(CustomLeagueValidationError):
        create_custom_league(conn, **{**_VALID, "sport": "tennis"})


@pytest.mark.parametrize("field", ["provider_league_id", "provider_league_name", "display_name"])
def test_create_rejects_blank_required_field(field):
    conn = _premium_db()
    with pytest.raises(CustomLeagueValidationError):
        create_custom_league(conn, **{**_VALID, field: "  "})


def test_update_only_touches_custom_rows(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    updated = update_custom_league(
        conn,
        "swe.1",
        provider_league_id="4379",
        provider_league_name="Allsvenskan (renamed)",
        display_name="Allsvenskan",
        sport="soccer",
    )
    assert updated["provider_league_name"] == "Allsvenskan (renamed)"


def test_update_rejects_builtin():
    conn = _premium_db()
    with pytest.raises(CustomLeagueProtectedError):
        update_custom_league(
            conn,
            "nfl",
            provider_league_id="x",
            provider_league_name="x",
            display_name="x",
            sport="football",
        )


def test_update_missing_league_is_404():
    conn = _premium_db()
    with pytest.raises(CustomLeagueNotFoundError):
        update_custom_league(
            conn,
            "does.not.exist",
            provider_league_id="x",
            provider_league_name="x",
            display_name="x",
            sport="soccer",
        )


def test_delete_removes_custom_row(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    delete_custom_league(conn, "swe.1")
    assert (
        conn.execute("SELECT 1 FROM leagues WHERE league_code = 'swe.1'").fetchone() is None
    )


def test_delete_rejects_builtin():
    conn = _premium_db()
    with pytest.raises(CustomLeagueProtectedError):
        delete_custom_league(conn, "nfl")
    # Built-in still present.
    assert conn.execute("SELECT 1 FROM leagues WHERE league_code = 'nfl'").fetchone() is not None


def test_delete_purges_cached_team_and_league_rows(monkeypatch):
    """Deleting a custom league drops its cached teams + league row (eqz.9).

    The create/refresh path scopes ``team_cache``/``league_cache`` to the league,
    so delete must do the same or it leaves ghosts behind. An unrelated league's
    cache must survive.
    """
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)

    # Caches the create/refresh path would populate for swe.1...
    conn.execute(
        """
        INSERT INTO team_cache
        (team_name, provider, provider_team_id, league, sport, last_seen)
        VALUES ('AIK', 'tsdb', '1', 'swe.1', 'soccer', '2026-01-01T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO league_cache
        (league_slug, provider, league_name, sport, team_count, last_refreshed)
        VALUES ('swe.1', 'tsdb', 'Swedish Allsvenskan', 'soccer', 1, '2026-01-01T00:00:00Z')
        """
    )
    # ...and a control row for an unrelated league that must survive.
    conn.execute(
        """
        INSERT INTO team_cache
        (team_name, provider, provider_team_id, league, sport, last_seen)
        VALUES ('Arsenal', 'espn', 'ars', 'eng.1', 'soccer', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    delete_custom_league(conn, "swe.1")

    # League row + both caches for swe.1 are gone.
    assert conn.execute("SELECT 1 FROM leagues WHERE league_code = 'swe.1'").fetchone() is None
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM team_cache WHERE league = 'swe.1'"
        ).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute("SELECT 1 FROM league_cache WHERE league_slug = 'swe.1'").fetchone() is None
    )
    # Unrelated league's cache is untouched.
    assert (
        conn.execute("SELECT 1 FROM team_cache WHERE league = 'eng.1'").fetchone() is not None
    )


def test_create_survives_restart(monkeypatch):
    """A novel custom code must survive re-running schema.sql (the restart path).

    schema.sql uses CREATE TABLE IF NOT EXISTS + INSERT OR REPLACE on built-in
    codes only, so a custom row's code is never in the REPLACE set.
    """
    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    conn.executescript(SCHEMA.read_text())  # simulate startup re-seed
    row = conn.execute(
        "SELECT is_custom, provider_league_name FROM leagues WHERE league_code = 'swe.1'"
    ).fetchone()
    assert row is not None
    assert row["is_custom"] == 1
    assert row["provider_league_name"] == "Swedish Allsvenskan"


# ---------------------------------------------------------------------------
# Live test-fetch / validation (eqz.3)
# ---------------------------------------------------------------------------


class _FakeTSDBClient:
    """Stand-in for TSDBClient that records the key and returns canned data."""

    league: dict | None = {"strLeague": "Swedish Allsvenskan", "strSport": "Soccer"}
    events: dict | None = {
        "events": [
            {
                "strEvent": "AIK vs Hammarby",
                "strHomeTeam": "AIK",
                "strAwayTeam": "Hammarby",
                "dateEvent": "2026-07-01",
                "strTimestamp": "2026-07-01T17:00:00",
            }
        ]
    }

    def __init__(self, api_key=None):
        self.api_key = api_key

    def lookup_league_raw(self, league_id):
        return self.league

    def get_next_events_raw(self, league_id):
        return self.events


def _patch_client(monkeypatch, cls=_FakeTSDBClient):
    import teamarr.providers.tsdb as tsdb_pkg

    monkeypatch.setattr(tsdb_pkg, "TSDBClient", cls)


def test_test_fetch_requires_premium(monkeypatch):
    conn = _db()  # no key
    with pytest.raises(CustomLeagueGateError):
        run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")


def test_test_fetch_returns_sample_events(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)
    result = run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")
    assert result["ok"] is True
    assert result["tsdb_league_name"] == "Swedish Allsvenskan"
    assert result["event_count"] == 1
    assert result["sample_events"][0]["home"] == "AIK"


def test_test_fetch_uses_premium_key(monkeypatch):
    conn = _premium_db()
    captured = {}

    class _Capturing(_FakeTSDBClient):
        def __init__(self, api_key=None):
            super().__init__(api_key)
            captured["key"] = api_key

    _patch_client(monkeypatch, _Capturing)
    run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")
    assert captured["key"] == "premium-abc123"


def test_test_fetch_unresolvable_id_is_validation_error(monkeypatch):
    conn = _premium_db()

    class _NoLeague(_FakeTSDBClient):
        league = None

    _patch_client(monkeypatch, _NoLeague)
    with pytest.raises(CustomLeagueValidationError):
        run_custom_league_test_fetch(conn, provider_league_id="999999", chosen_sport="soccer")


def test_test_fetch_sport_mismatch_rejected(monkeypatch):
    conn = _premium_db()

    class _Cricket(_FakeTSDBClient):
        league = {"strLeague": "Some Cricket", "strSport": "Cricket"}

    _patch_client(monkeypatch, _Cricket)
    with pytest.raises(CustomLeagueValidationError) as exc:
        run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")
    assert "mismatch" in str(exc.value).lower()


def test_test_fetch_no_events_is_ok_not_error(monkeypatch):
    conn = _premium_db()

    class _Empty(_FakeTSDBClient):
        events = {"events": []}

    _patch_client(monkeypatch, _Empty)
    result = run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")
    assert result["ok"] is True
    assert result["event_count"] == 0
    assert result["sample_events"] == []


# ---------------------------------------------------------------------------
# Route exception → HTTP mapping (eqz.2/eqz.3) — DB-free, no real writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,status",
    [
        (CustomLeagueGateError("locked"), 403),
        (CustomLeagueProtectedError("builtin"), 403),
        (CustomLeagueNotFoundError("missing"), 404),
        (CustomLeagueValidationError("bad"), 400),
    ],
)
def test_route_exception_mapping(exc, status):
    from fastapi import HTTPException

    from teamarr.api.routes.leagues import _raise_http

    with pytest.raises(HTTPException) as caught:
        _raise_http(exc)
    assert caught.value.status_code == status
    assert caught.value.detail == str(exc)


def test_route_mapping_reraises_unknown():
    from teamarr.api.routes.leagues import _raise_http

    sentinel = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        _raise_http(sentinel)


# ---------------------------------------------------------------------------
# Create-time live guardrail (eqz.3 wired into eqz.2)
# ---------------------------------------------------------------------------


def test_create_blocks_when_zero_events(monkeypatch):
    conn = _premium_db()

    class _Empty(_FakeTSDBClient):
        events = {"events": []}

    _patch_client(monkeypatch, _Empty)
    with pytest.raises(CustomLeagueValidationError) as exc:
        create_custom_league(conn, **_VALID)
    assert "no upcoming events" in str(exc.value).lower()
    # Nothing was written.
    assert conn.execute("SELECT 1 FROM leagues WHERE league_code = 'swe.1'").fetchone() is None


def test_list_custom_leagues_returns_only_custom(monkeypatch):
    from teamarr.database.leagues import list_custom_leagues

    conn = _premium_db()
    _patch_client(monkeypatch)
    assert list_custom_leagues(conn) == []  # none yet; built-ins excluded
    create_custom_league(conn, **_VALID)
    rows = list_custom_leagues(conn)
    assert len(rows) == 1
    assert rows[0]["league_code"] == "swe.1"
    assert rows[0]["provider"] == "tsdb"
    # Built-ins (is_custom=0) are never listed.
    assert all(r["league_code"] != "nfl" for r in rows)


def test_create_allow_empty_override(monkeypatch):
    conn = _premium_db()

    class _Empty(_FakeTSDBClient):
        events = {"events": []}

    _patch_client(monkeypatch, _Empty)
    row = create_custom_league(conn, **_VALID, allow_empty=True)
    assert row["is_custom"] == 1


def test_create_enforces_tsdb_sport_cross_check(monkeypatch):
    conn = _premium_db()

    class _Cricket(_FakeTSDBClient):
        league = {"strLeague": "Swedish Allsvenskan", "strSport": "Cricket"}

    _patch_client(monkeypatch, _Cricket)
    # User selected soccer but TSDB classifies the id as cricket → blocked.
    with pytest.raises(CustomLeagueValidationError) as exc:
        create_custom_league(conn, **_VALID)
    assert "mismatch" in str(exc.value).lower()
    assert conn.execute("SELECT 1 FROM leagues WHERE league_code = 'swe.1'").fetchone() is None


def test_validator_reports_resolution_metadata(monkeypatch):
    conn = _premium_db()
    _patch_client(monkeypatch)
    # Matching name → name_matches True; resolved_via surfaced for id/name debug.
    ok = run_custom_league_test_fetch(
        conn,
        provider_league_id="4379",
        chosen_sport="soccer",
        provider_league_name="swedish allsvenskan",  # case-insensitive match
    )
    assert ok["resolved_via"] == "eventsnextleague"
    assert ok["name_matches"] is True

    # Wrong name → name_matches False (helps distinguish a bad name from a bad id).
    bad = run_custom_league_test_fetch(
        conn,
        provider_league_id="4379",
        chosen_sport="soccer",
        provider_league_name="Totally Wrong Name",
    )
    assert bad["name_matches"] is False

    # No name supplied → name_matches stays None (not checked).
    none = run_custom_league_test_fetch(conn, provider_league_id="4379", chosen_sport="soccer")
    assert none["name_matches"] is None


# ---------------------------------------------------------------------------
# Scoped team-cache refresh on create (eqz.4)
# ---------------------------------------------------------------------------

import contextlib  # noqa: E402

from teamarr.core import Team  # noqa: E402


def _shared_factory(conn: sqlite3.Connection):
    """A get_db-shaped factory bound to one in-memory conn (commits, never closes)."""

    @contextlib.contextmanager
    def factory():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return factory


class _FakeTeamProvider:
    """Provider stub returning a fixed roster for any league."""

    def __init__(self, teams: list[Team], supports: bool = True):
        self._teams = teams
        self._supports = supports

    def supports_league(self, league: str) -> bool:
        return self._supports

    def get_league_teams(self, league: str) -> list[Team]:
        return self._teams


def _mk_team(tid: str, name: str, league: str) -> Team:
    return Team(
        id=tid,
        provider="tsdb",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league=league,
        sport="soccer",
    )


def _patch_provider(monkeypatch, provider):
    import teamarr.providers as providers_pkg

    monkeypatch.setattr(
        providers_pkg.ProviderRegistry,
        "get",
        staticmethod(lambda name: provider if name == "tsdb" else None),
    )


def test_refresh_league_populates_teams_and_counts(monkeypatch):
    from teamarr.consumers.cache.refresh import CacheRefresher

    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)  # swe.1, tsdb, soccer

    provider = _FakeTeamProvider(
        [_mk_team("1", "AIK", "swe.1"), _mk_team("2", "Hammarby", "swe.1")]
    )
    _patch_provider(monkeypatch, provider)

    result = CacheRefresher(db_factory=_shared_factory(conn)).refresh_league("swe.1")
    assert result == {"success": True, "league_code": "swe.1", "team_count": 2, "error": None}

    cached = conn.execute(
        "SELECT COUNT(*) AS n FROM team_cache WHERE league = 'swe.1'"
    ).fetchone()["n"]
    assert cached == 2
    row = conn.execute(
        "SELECT cached_team_count, last_cache_refresh FROM leagues WHERE league_code = 'swe.1'"
    ).fetchone()
    assert row["cached_team_count"] == 2
    assert row["last_cache_refresh"] is not None


def test_refresh_league_does_not_wipe_other_leagues(monkeypatch):
    from teamarr.consumers.cache.refresh import CacheRefresher

    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)
    # A pre-existing team from a different league must survive the scoped refresh.
    conn.execute(
        """
        INSERT INTO team_cache
        (team_name, provider, provider_team_id, league, sport, last_seen)
        VALUES ('Arsenal', 'espn', 'ars', 'eng.1', 'soccer', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    provider = _FakeTeamProvider([_mk_team("1", "AIK", "swe.1")])
    _patch_provider(monkeypatch, provider)
    CacheRefresher(db_factory=_shared_factory(conn)).refresh_league("swe.1")

    assert (
        conn.execute("SELECT 1 FROM team_cache WHERE league = 'eng.1'").fetchone() is not None
    )
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM team_cache WHERE league = 'swe.1'").fetchone()["n"]
        == 1
    )


def test_refresh_league_unknown_league_fails_gracefully():
    from teamarr.consumers.cache.refresh import CacheRefresher

    conn = _premium_db()
    result = CacheRefresher(db_factory=_shared_factory(conn)).refresh_league("nope.1")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_refresh_league_provider_error_is_graceful(monkeypatch):
    from teamarr.consumers.cache.refresh import CacheRefresher

    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)

    class _Boom:
        def supports_league(self, league):
            return True

        def get_league_teams(self, league):
            raise RuntimeError("TSDB down")

    _patch_provider(monkeypatch, _Boom())
    result = CacheRefresher(db_factory=_shared_factory(conn)).refresh_league("swe.1")
    assert result["success"] is False
    assert "tsdb down" in result["error"].lower()
    # League row untouched (still 0 cached).
    assert (
        conn.execute(
            "SELECT cached_team_count FROM leagues WHERE league_code = 'swe.1'"
        ).fetchone()["cached_team_count"]
        == 0
    )


def test_refresh_league_unresolvable_mapping_fails(monkeypatch):
    """A league the provider can't resolve must fail, not report a silent zero.

    This is the regression guard for the stale-mapping bug: a custom league
    committed but not yet in the in-memory mapping resolves no teams, which must
    surface as success=False (not the misleading success=True, team_count=0).
    """
    from teamarr.consumers.cache.refresh import CacheRefresher

    conn = _premium_db()
    _patch_client(monkeypatch)
    create_custom_league(conn, **_VALID)

    # Provider has a roster but reports the league as unsupported (mapping miss).
    provider = _FakeTeamProvider([_mk_team("1", "AIK", "swe.1")], supports=False)
    _patch_provider(monkeypatch, provider)

    result = CacheRefresher(db_factory=_shared_factory(conn)).refresh_league("swe.1")
    assert result["success"] is False
    assert "resolve" in result["error"].lower()
    # Nothing cached, league count untouched.
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM team_cache WHERE league = 'swe.1'").fetchone()["n"]
        == 0
    )


def test_refresh_custom_league_teams_wrapper_never_raises(monkeypatch):
    """The service wrapper swallows refresher explosions into a result dict."""
    import teamarr.services.custom_leagues as svc

    class _Exploding:
        def refresh_league(self, code):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(
        "teamarr.consumers.cache.refresh.CacheRefresher", lambda *a, **k: _Exploding()
    )
    out = svc.refresh_custom_league_teams("swe.1")
    assert out["success"] is False
    assert "kaboom" in out["error"].lower()

