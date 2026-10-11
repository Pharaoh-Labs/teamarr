"""Leagues offered by the template preview picker (#993).

A league only discovered from a provider can be subscribed to, so it has to be
previewable; and a template's preview opens on a league the template is used
for, not on NBA.
"""

import json

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db

client = TestClient(app)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO league_cache (league_slug, provider, league_name, sport, team_count) "
            "VALUES ('eng.w.1', 'espn', 'English Women''s Super League', 'soccer', 14)"
        )
        ids = {}
        for name, kind in (("Soccer", "event"), ("Hoops", "event"), ("Any", "event"),
                           ("Club", "team")):
            cur = conn.execute(
                "INSERT INTO templates (name, template_type) VALUES (?, ?)", (name, kind)
            )
            ids[name] = cur.lastrowid
        conn.execute(
            "INSERT INTO subscription_templates (template_id, sports) VALUES (?, ?)",
            (ids["Soccer"], json.dumps(["soccer"])),
        )
        conn.execute(
            "INSERT INTO subscription_templates (template_id, leagues) VALUES (?, ?)",
            (ids["Hoops"], json.dumps(["wnba"])),
        )
        conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (ids["Any"],))
        conn.commit()
    return ids


def _get(template_id=None):
    params = {} if template_id is None else {"template_id": template_id}
    resp = client.get("/api/v1/variables/sample-leagues", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _subscribe(*codes):
    with get_db() as conn:
        conn.execute("UPDATE sports_subscription SET leagues = ? WHERE id = 1",
                     (json.dumps(list(codes)),))
        conn.commit()


def test_a_discovered_league_is_offered_alongside_configured_ones(db):
    slugs = {lg["slug"] for lg in _get()["leagues"]}
    assert {"eng.w.1", "nba", "eng.1"} <= slugs


def test_a_subscribed_discovered_league_is_in_the_default_view(db):
    _subscribe("eng.w.1")
    assert "eng.w.1" in _get()["subscribed_slugs"]


def test_no_template_means_no_opinion(db):
    assert _get()["default_slug"] is None
    assert _get(db["Any"])["default_slug"] is None


def test_a_league_assignment_names_the_default(db):
    assert _get(db["Hoops"])["default_slug"] == "wnba"


def test_a_sport_assignment_prefers_a_subscribed_league_of_that_sport(db):
    by_slug = {lg["slug"]: lg for lg in _get()["leagues"]}
    unsubscribed = _get(db["Soccer"])["default_slug"]
    assert by_slug[unsubscribed]["sport"] == "soccer"
    _subscribe("nba", "eng.w.1")
    assert _get(db["Soccer"])["default_slug"] == "eng.w.1"


def test_a_team_template_opens_on_a_league_its_teams_play_in(db):
    with get_db() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(teams)")}
        assert {"template_id", "primary_league"} <= cols
        conn.execute(
            "INSERT INTO teams (provider, provider_team_id, primary_league, leagues, sport, "
            "team_name, channel_id, template_id) "
            "VALUES ('espn', '360', 'eng.1', ?, 'soccer', 'Manchester United', 'ManU.eng1', ?)",
            (json.dumps(["eng.1"]), db["Club"]),
        )
        conn.commit()
    assert _get(db["Club"])["default_slug"] == "eng.1"
