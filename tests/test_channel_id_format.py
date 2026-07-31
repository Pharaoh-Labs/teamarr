"""channel_id_format drives team import, not just the bulk dialog (#522).

The setting was persisted and editable but nothing read it: import hardcoded
PascalCase and bulk-regenerate used its own dialog value. These pin that both
paths now render through one implementation.
"""

import pytest

from teamarr.database.connection import get_db, init_db
from teamarr.database.teams import render_channel_id
from teamarr.services.team_import import ImportTeam, bulk_import_teams


class TestRenderChannelId:
    def test_default_template_matches_the_old_hardcoded_shape(self):
        """The wiring must be a no-op for anyone on defaults."""
        assert (
            render_channel_id(
                "{team_name|pascal}.{league_id}",
                team_name="Michigan Wolverines",
                league_id="ncaam",
            )
            == "MichiganWolverines.ncaam"
        )

    def test_legacy_pascal_alias_still_works(self):
        assert (
            render_channel_id(
                "{team_name_pascal}.{league_id}", team_name="Chicago Cubs", league_id="mlb"
            )
            == "ChicagoCubs.mlb"
        )

    def test_lowercase_template_is_slugified(self):
        assert (
            render_channel_id(
                "{team_name}-{league_id}", team_name="Chicago Cubs", league_id="mlb"
            )
            == "chicago-cubs-mlb"
        )

    def test_mixed_case_template_keeps_casing(self):
        assert (
            render_channel_id(
                "{league}.{team_abbrev}",
                team_name="Chicago Cubs",
                team_abbrev="CHC",
                league_display="MLB",
            )
            == "MLB.chc"
        )

    def test_all_tokens_render(self):
        out = render_channel_id(
            "{team_name}.{team_abbrev}.{provider_team_id}.{league_id}.{sport}",
            team_name="Chicago Cubs",
            team_abbrev="CHC",
            provider_team_id="16",
            league_id="mlb",
            sport="Baseball",
        )
        assert out == "chicago-cubs.chc.16.mlb.baseball"

    def test_empty_render_is_reported_as_empty(self):
        """Caller decides the fallback; the renderer doesn't invent one."""
        assert render_channel_id("{team_abbrev}", team_name="Chicago Cubs") == ""


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    yield


def _team(name="Chicago Cubs", abbrev="CHC", team_id="16") -> ImportTeam:
    return ImportTeam(
        team_name=name,
        team_abbrev=abbrev,
        provider="espn",
        provider_team_id=team_id,
        league="mlb",
        sport="baseball",
        logo_url=None,
    )


def _channel_ids() -> list[str]:
    with get_db() as conn:
        return [r["channel_id"] for r in conn.execute("SELECT channel_id FROM teams")]


def test_import_uses_the_default_format_unchanged(db):
    with get_db() as conn:
        bulk_import_teams(conn, [_team()])
        conn.commit()
    assert _channel_ids() == ["ChicagoCubs.mlb"]


def test_import_honors_a_custom_channel_id_format(db):
    with get_db() as conn:
        conn.execute("UPDATE settings SET channel_id_format = '{team_abbrev}-{league_id}'")
        conn.commit()
        bulk_import_teams(conn, [_team()])
        conn.commit()
    assert _channel_ids() == ["chc-mlb"]


def test_import_falls_back_when_template_renders_empty(db):
    """A template that produces nothing must not write an empty channel_id."""
    with get_db() as conn:
        conn.execute("UPDATE settings SET channel_id_format = '{provider_team_id}'")
        conn.commit()
        bulk_import_teams(conn, [_team(team_id="")])
        conn.commit()
    assert _channel_ids() == ["ChicagoCubs.mlb"]


def test_collision_still_disambiguates_with_provider_id(db):
    """Two same-named teams in one league keep unique ids under a custom format."""
    with get_db() as conn:
        conn.execute("UPDATE settings SET channel_id_format = '{team_abbrev}-{league_id}'")
        conn.commit()
        bulk_import_teams(
            conn,
            [_team(team_id="16"), _team(name="Chicago Cubs", abbrev="CHC", team_id="17")],
        )
        conn.commit()
    ids = sorted(_channel_ids())
    assert ids == ["chc-mlb", "chc-mlb.17"], ids
