"""Exception keyword hierarchy (#931).

When several keywords matched one stream, the first match won outright, and
within one kind of evidence "first" was alphabetical by label. With *Spanish*
set to Ignore and *4K* to Sub-Consolidate, a Spanish 4K stream went to the 4K
channel because "4K" sorts before "Spanish".

Two rules now sit on top of the evidence order: an Ignore keyword always wins
(a pin excepted), and otherwise ties go to the keyword higher in the user's
order.
"""

import pytest

from teamarr.database.channels import check_exception_keyword
from teamarr.database.exception_keywords import (
    ExceptionKeyword,
    create_keyword,
    get_all_keywords,
    get_keywords_by_behavior,
    set_keyword_order,
)


def kw(label, terms="", behavior="consolidate", **sources):
    return ExceptionKeyword(label=label, match_terms=terms, behavior=behavior, **sources)


FOUR_K = kw("4K", "4k, uhd")
SPANISH_IGNORE = kw("Spanish", "Spanish, En Español, (ESP)", "ignore")
MANNING = kw("ManningCast", "manningcast, manning cast")


class TestIgnoreAlwaysWins:
    def test_ignore_beats_an_earlier_keyword_in_the_same_evidence(self):
        """The reported shape: both terms are in the stream name and 4K comes
        first in the list."""
        result = check_exception_keyword(
            "ESPN Deportes 4K (ESP): Yankees vs Red Sox", [FOUR_K, SPANISH_IGNORE]
        )
        assert result == ("Spanish", "ignore")

    def test_ignore_by_group_beats_a_name_match(self):
        """Name evidence is checked before group evidence, so a stream filed
        under an ignored M3U group used to be kept whenever its name carried
        any other keyword."""
        es_group = kw("ES", behavior="ignore", m3u_group_pattern=r"^ES\|")
        result = check_exception_keyword(
            "Match 4K", [FOUR_K, es_group], m3u_group_name="ES| DAZN PPV"
        )
        assert result == ("ES", "ignore")

    def test_ignore_by_guide_programme_beats_a_name_match(self):
        result = check_exception_keyword(
            "ESPN 4K", [FOUR_K, SPANISH_IGNORE], program_title="MLB Baseball En Español"
        )
        assert result == ("Spanish", "ignore")

    def test_a_pinned_stream_outranks_ignore(self):
        """A pin is the most specific thing a user can say about one stream."""
        pinned = kw("4K", "4k", streams=[{"id": 42, "name": "feed"}])
        result = check_exception_keyword(
            "Yankees vs Red Sox (ESP)", [pinned, SPANISH_IGNORE], stream_id=42
        )
        assert result == ("4K", "consolidate")

    def test_ignore_still_respects_the_event_name_guard(self):
        """#803: 'Spanish' must not fire on the Spanish Grand Prix, so the
        4K keyword is the only real match."""
        result = check_exception_keyword(
            "F1: Spanish Grand Prix 4K", [FOUR_K, SPANISH_IGNORE], "Spanish Grand Prix"
        )
        assert result == ("4K", "consolidate")

    def test_a_non_ignore_keyword_does_not_get_the_same_privilege(self):
        """Only Ignore jumps the evidence order: a Sub-Consolidate keyword
        matched by group still loses to one matched by name."""
        es_group = kw("ES", m3u_group_pattern=r"^ES\|")
        result = check_exception_keyword(
            "Match 4K", [es_group, FOUR_K], m3u_group_name="ES| DAZN PPV"
        )
        assert result == ("4K", "consolidate")

    def test_single_matches_are_unchanged(self):
        keywords = [FOUR_K, SPANISH_IGNORE, MANNING]
        assert check_exception_keyword("Game 4K", keywords) == ("4K", "consolidate")
        assert check_exception_keyword("Game (ESP)", keywords) == ("Spanish", "ignore")
        assert check_exception_keyword("Game", keywords) == (None, None)


class TestUserOrderBreaksTies:
    def test_the_higher_keyword_wins(self):
        stream = "ESPN2 4K: ManningCast - Broncos at Chiefs"
        assert check_exception_keyword(stream, [FOUR_K, MANNING])[0] == "4K"
        assert check_exception_keyword(stream, [MANNING, FOUR_K])[0] == "ManningCast"

    def test_unordered_keywords_load_alphabetically_as_before(self, db_conn):
        for label in ("ZzzSpanish", "Zzz4K", "ZzzManningCast"):
            create_keyword(db_conn, label=label, match_terms=label)
        labels = [k.label for k in get_all_keywords(db_conn) if k.label.startswith("Zzz")]
        assert labels == ["Zzz4K", "ZzzManningCast", "ZzzSpanish"]

    def test_set_order_is_what_matching_sees(self, db_conn):
        ids = {
            label: create_keyword(db_conn, label=label, match_terms=terms)
            for label, terms in (("Zzz4K", "4k"), ("ZzzManning", "manningcast"))
        }
        stream = "ESPN2 4K: ManningCast - Broncos at Chiefs"
        mine = lambda: [k for k in get_all_keywords(db_conn) if k.label.startswith("Zzz")]  # noqa: E731
        assert check_exception_keyword(stream, mine())[0] == "Zzz4K"

        set_keyword_order(db_conn, [ids["ZzzManning"], ids["Zzz4K"]])

        assert [k.label for k in mine()] == ["ZzzManning", "Zzz4K"]
        assert check_exception_keyword(stream, mine())[0] == "ZzzManning"
        assert [k.label for k in get_keywords_by_behavior(db_conn, "consolidate")][:2] == [
            "ZzzManning",
            "Zzz4K",
        ]

    def test_keywords_left_out_of_an_order_sort_after_it_by_label(self, db_conn):
        a = create_keyword(db_conn, label="ZzzA", match_terms="a")
        create_keyword(db_conn, label="ZzzB", match_terms="b")
        c = create_keyword(db_conn, label="ZzzC", match_terms="c")
        db_conn.execute(
            "DELETE FROM consolidation_exception_keywords WHERE label NOT LIKE 'Zzz%'"
        )

        assert set_keyword_order(db_conn, [c, a]) == 2

        assert [k.label for k in get_all_keywords(db_conn)] == ["ZzzC", "ZzzA", "ZzzB"]

    def test_a_database_without_the_column_reads_alphabetically(self):
        """Partial schemas (and a DB not yet reconciled) have no sort_order."""
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE consolidation_exception_keywords (id INTEGER PRIMARY KEY,"
            " created_at TIMESTAMP, label TEXT, match_terms TEXT, behavior TEXT, enabled BOOLEAN)"
        )
        conn.executemany(
            "INSERT INTO consolidation_exception_keywords (label, match_terms, behavior, enabled)"
            " VALUES (?, ?, 'consolidate', 1)",
            [("Spanish", "spanish"), ("4K", "4k")],
        )
        assert [k.label for k in get_all_keywords(conn)] == ["4K", "Spanish"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.database.connection import init_db

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return TestClient(app)


class TestOrderApi:
    def _create(self, client, label, terms):
        resp = client.post("/api/v1/keywords", json={"label": label, "match_terms": terms})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_put_order_returns_the_list_in_its_new_order(self, client):
        four_k = self._create(client, "Zzz4K", "4k")
        manning = self._create(client, "ZzzManning", "manningcast")

        resp = client.put("/api/v1/keywords/order", json={"keyword_ids": [manning, four_k]})

        assert resp.status_code == 200, resp.text
        labels = [k["label"] for k in resp.json()["keywords"]]
        assert labels[:2] == ["ZzzManning", "Zzz4K"]
        assert resp.json()["keywords"][0]["sort_order"] == 0
        listed = client.get("/api/v1/keywords?include_disabled=true").json()["keywords"]
        assert [k["label"] for k in listed][:2] == ["ZzzManning", "Zzz4K"]

    def test_unknown_id_is_rejected_and_nothing_changes(self, client):
        four_k = self._create(client, "Zzz4K", "4k")

        resp = client.put("/api/v1/keywords/order", json={"keyword_ids": [four_k, 987654]})

        assert resp.status_code == 404
        listed = client.get("/api/v1/keywords?include_disabled=true").json()["keywords"]
        assert all(k["sort_order"] is None for k in listed)

    def test_order_route_is_not_swallowed_by_the_id_route(self, client):
        """`/order` must be declared before `/{keyword_id}`."""
        assert client.put("/api/v1/keywords/order", json={"keyword_ids": []}).status_code == 422
