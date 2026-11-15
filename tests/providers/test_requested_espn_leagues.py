"""Requested ESPN leagues survive startup and route through the standard provider."""

import pytest

from teamarr.database import get_db, init_db
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services.league_mappings import LeagueMappingService


@pytest.mark.parametrize(
    ("league", "sport", "path", "alias", "import_enabled"),
    [
        ("uefa.wchampions", "soccer", "soccer", "UWCL", 1),
        (
            "womens-college-field-hockey",
            "field hockey",
            "field-hockey",
            "NCAAWFH",
            0,
        ),
    ],
)
def test_requested_leagues_are_seeded_on_existing_installations(
    tmp_path, monkeypatch, league, sport, path, alias, import_enabled
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "leagues.db"))
    init_db()
    with get_db() as conn:
        # Simulate an existing installation from before these registry rows.
        conn.execute("DELETE FROM leagues WHERE league_code = ?", (league,))
        conn.commit()
    init_db()
    source = LeagueMappingService(get_db)
    provider = ESPNProvider(league_mapping_source=source)
    assert provider.supports_league(league)
    assert provider._get_sport_league_from_db(league) == (path, league)
    assert provider._get_sport(league) == sport
    assert source.get_league_alias(league) == alias
    with get_db() as conn:
        row = conn.execute(
            "SELECT import_enabled, event_type FROM leagues WHERE league_code = ?", (league,)
        ).fetchone()
        assert tuple(row) == (import_enabled, "team_vs_team")
        assert (
            conn.execute(
                "SELECT display_name FROM sports WHERE sport_code = ?", (sport,)
            ).fetchone()[0]
            == sport.title()
        )
