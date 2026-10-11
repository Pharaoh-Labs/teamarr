"""An exception keyword's match source can be cleared through the API (#1010).

The match-sources editor sends ``null`` for an emptied regex. The update
route read ``None`` as "field not provided" and left the old value in place,
so a regex, once set, could never be removed. A field the body names as null
(or as an empty string/list) is now a clear; a field the body omits is still
left alone.
"""

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.database.connection import init_db

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return TestClient(app)


def _create(client, **body):
    resp = client.post("/api/v1/keywords", json={"label": "ES", "match_terms": "", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _stored(client, keyword_id):
    """The keyword as the list reports it (the list also carries the seeded rows)."""
    keywords = client.get("/api/v1/keywords").json()["keywords"]
    return next(k for k in keywords if k["id"] == keyword_id)


def _put(client, keyword_id, body):
    resp = client.put(f"/api/v1/keywords/{keyword_id}", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestClearingARegex:
    def test_null_clears_the_m3u_group_regex(self, client):
        kw = _create(client, match_terms="spanish", m3u_group_pattern=r"^ES\|")

        after = _put(client, kw, {"m3u_group_pattern": None})

        assert after["m3u_group_pattern"] is None
        assert _stored(client, kw)["m3u_group_pattern"] is None

    def test_null_clears_the_stream_regex(self, client):
        kw = _create(client, match_terms="spanish", stream_pattern=r"\(MX\)")

        assert _put(client, kw, {"stream_pattern": None})["stream_pattern"] is None

    def test_empty_string_still_clears(self, client):
        kw = _create(client, match_terms="spanish", m3u_group_pattern=r"^ES\|")

        assert _put(client, kw, {"m3u_group_pattern": ""})["m3u_group_pattern"] is None

    def test_an_omitted_regex_is_left_alone(self, client):
        kw = _create(client, match_terms="spanish", m3u_group_pattern=r"^ES\|")

        after = _put(client, kw, {"enabled": False})

        assert after["m3u_group_pattern"] == r"^ES\|"
        assert after["enabled"] is False

    def test_the_editor_payload_clears_one_and_keeps_the_other(self, client):
        """The editor sends every source field; emptied ones arrive as null."""
        kw = _create(client, match_terms="", m3u_group_pattern=r"^ES\|", stream_pattern=r"\(MX\)")

        after = _put(
            client,
            kw,
            {
                "m3u_group_pattern": None,
                "m3u_groups": [],
                "stream_pattern": r"\(MX\)",
                "streams": [],
                "event_group_ids": [],
            },
        )

        assert after["m3u_group_pattern"] is None
        assert after["stream_pattern"] == r"\(MX\)"


class TestClearingPickedSources:
    def test_null_clears_picked_groups(self, client):
        kw = _create(client, match_terms="spanish", m3u_groups=[{"id": 33, "name": "ES| VIX"}])

        assert _put(client, kw, {"m3u_groups": None})["m3u_groups"] == []

    def test_null_clears_event_groups(self, client):
        kw = _create(client, match_terms="spanish", event_group_ids=[17])

        assert _put(client, kw, {"event_group_ids": None})["event_group_ids"] == []


class TestTheLastSourceCannotBeCleared:
    def test_clearing_the_only_source_is_refused(self, client):
        kw = _create(client, match_terms="", m3u_group_pattern=r"^ES\|")

        resp = client.put(f"/api/v1/keywords/{kw}", json={"m3u_group_pattern": None})

        assert resp.status_code == 400
        assert _stored(client, kw)["m3u_group_pattern"] == r"^ES\|"
