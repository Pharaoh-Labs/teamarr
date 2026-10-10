"""A team pinned block on a racing team is refused (#1019).

Racing events carry a placeholder team named after the event in
home_team/away_team, so a constructor name never matches a channel.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db
from teamarr.database import numbering_exceptions as ne

client = TestClient(app)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as c:
        c.execute("DELETE FROM team_cache")
        c.executemany(
            "INSERT INTO team_cache (team_name, provider, provider_team_id, league, sport) "
            "VALUES (?, 'espn', ?, ?, ?)",
            [
                ("Red Bull", "rb", "f1", "motor sports"),
                ("Red Bull Alt", "rb2", "f1", "Motor Sports"),
                ("Penske", "pen", "indycar", "racing"),
                ("Mystery Team", "mys", "f1", "open wheel"),
                ("Detroit Lions", "8", "nfl", "football"),
            ],
        )
        yield c


@pytest.mark.parametrize("team_id", ["rb", "rb2", "pen", "mys"])
def test_racing_team_pin_is_refused(conn, team_id):
    with pytest.raises(ne.RacingTeamPin, match="league block"):
        ne.add_numbering_exception(
            conn, scope="team", start=800, provider="espn", provider_team_id=team_id
        )
    assert conn.execute("SELECT COUNT(*) FROM numbering_exceptions").fetchone()[0] == 0


def test_non_racing_team_pin_still_added(conn):
    exc = ne.add_numbering_exception(
        conn, scope="team", start=800, provider="espn", provider_team_id="8"
    )
    assert exc is not None and exc.team_name == "Detroit Lions"


def test_api_returns_400_with_message(conn):
    conn.commit()
    resp = client.post(
        "/api/v1/numbering-exceptions",
        json={"scope": "team", "start": 800, "provider": "espn", "team_id": "rb"},
    )
    assert resp.status_code == 400, resp.text
    assert "racing team" in resp.json()["detail"]
    assert "league block" in resp.json()["detail"]
