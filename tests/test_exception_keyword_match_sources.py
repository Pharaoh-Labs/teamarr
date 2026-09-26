"""Exception keyword match sources (#893): M3U group, pinned streams, stream
regex and event group, checked after or before the stream-name terms by how
specific the evidence is.
"""

from types import SimpleNamespace

import pytest

from teamarr.consumers.enforcement.keywords import KeywordEnforcer
from teamarr.consumers.event_group_processor.stream_fetcher import stream_m3u_group
from teamarr.database.channels import (
    add_stream_to_channel,
    check_exception_keyword,
    create_managed_channel,
    get_channel_streams,
    update_stream_m3u_group,
)
from teamarr.database.exception_keywords import (
    ExceptionKeyword,
    create_keyword,
    get_keyword,
    update_keyword,
)


def kw(label, terms="", **sources):
    return ExceptionKeyword(label=label, match_terms=terms, **sources)


class TestSourcesAlone:
    def test_pinned_stream(self):
        keywords = [kw("ES", streams=[{"id": 42, "name": "Some feed"}])]
        assert check_exception_keyword("Some feed", keywords, stream_id=42) == ("ES", "consolidate")
        assert check_exception_keyword("Some feed", keywords, stream_id=43) == (None, None)

    def test_stream_regex(self):
        keywords = [kw("ES", stream_pattern=r"\(MX\)")]
        assert check_exception_keyword("(MX) (VIX 02) | Cruz Azul vs. Toluca", keywords)[0] == "ES"
        assert check_exception_keyword("Cruz Azul vs. Toluca", keywords)[0] is None

    def test_stream_regex_is_case_insensitive(self):
        assert (
            check_exception_keyword("dazn es | event", [kw("ES", stream_pattern="DAZN ES")])[0]
            == "ES"
        )

    def test_picked_m3u_group(self):
        keywords = [kw("ES", m3u_groups=[{"id": 33, "name": "ES| VIX PPV"}])]
        assert check_exception_keyword("Cruz Azul vs. Toluca", keywords, m3u_group_id=33)[0] == "ES"
        assert check_exception_keyword("Cruz Azul vs. Toluca", keywords, m3u_group_id=34)[0] is None

    def test_m3u_group_regex(self):
        keywords = [kw("ES", m3u_group_pattern=r"^(ES|LA)\|")]
        assert check_exception_keyword("x", keywords, m3u_group_name="ES| DAZN PPV")[0] == "ES"
        assert check_exception_keyword("x", keywords, m3u_group_name="UK| SPORT")[0] is None

    def test_event_group(self):
        keywords = [kw("ES", event_group_ids=[17])]
        assert check_exception_keyword("x", keywords, event_group_id=17)[0] == "ES"
        assert check_exception_keyword("x", keywords, event_group_id=16)[0] is None

    def test_behavior_is_returned(self):
        keywords = [ExceptionKeyword(label="ES", behavior="separate", event_group_ids=[1])]
        assert check_exception_keyword("x", keywords, event_group_id=1) == ("ES", "separate")

    def test_source_only_keyword_never_matches_names(self):
        # match_terms '' must not turn into a term that matches everything
        keywords = [kw("ES", m3u_group_pattern="^ES\\|")]
        assert check_exception_keyword("Arsenal v Chelsea", keywords) == (None, None)

    def test_invalid_stored_regex_is_skipped(self):
        keywords = [kw("Bad", stream_pattern="(", m3u_group_pattern="["), kw("ES", "Spanish")]
        assert check_exception_keyword("Spanish feed", keywords, m3u_group_name="ES|")[0] == "ES"


class TestPrecedence:
    """Most specific evidence wins, across keywords."""

    def test_pin_beats_name(self):
        keywords = [kw("Spanish", "Spanish"), kw("EN", streams=[{"id": 7, "name": None}])]
        assert check_exception_keyword("Spanish feed", keywords, stream_id=7)[0] == "EN"

    def test_name_terms_beat_group(self):
        keywords = [kw("GRP", m3u_group_pattern="^ES"), kw("4K", "4K")]
        assert check_exception_keyword("Match 4K", keywords, m3u_group_name="ES| X")[0] == "4K"

    def test_name_regex_beats_group(self):
        keywords = [kw("GRP", m3u_groups=[{"id": 1, "name": "g"}]), kw("RX", stream_pattern="uhd")]
        assert check_exception_keyword("Match UHD", keywords, m3u_group_id=1)[0] == "RX"

    def test_terms_beat_regex_across_keywords(self):
        keywords = [kw("RX", stream_pattern="feed"), kw("TERM", "Feed")]
        assert check_exception_keyword("Spanish Feed", keywords)[0] == "TERM"

    def test_program_title_beats_group(self):
        keywords = [kw("GRP", event_group_ids=[5]), kw("MC", "ManningCast")]
        assert (
            check_exception_keyword(
                "ESPN 2", keywords, program_title="MNF ManningCast", event_group_id=5
            )[0]
            == "MC"
        )

    def test_stream_regex_does_not_read_program_title(self):
        keywords = [kw("RX", stream_pattern="manningcast")]
        assert check_exception_keyword("ESPN 2", keywords, program_title="ManningCast")[0] is None

    def test_picked_group_beats_group_regex(self):
        keywords = [
            kw("RX", m3u_group_pattern="^ES"),
            kw("PICK", m3u_groups=[{"id": 9, "name": "ES|"}]),
        ]
        assert (
            check_exception_keyword("x", keywords, m3u_group_id=9, m3u_group_name="ES|")[0]
            == "PICK"
        )

    def test_group_regex_beats_event_group(self):
        keywords = [kw("EG", event_group_ids=[3]), kw("RX", m3u_group_pattern="^ES")]
        assert (
            check_exception_keyword("x", keywords, m3u_group_name="ES|", event_group_id=3)[0]
            == "RX"
        )


class TestEventNameGuard:
    """#803 guards match terms; a user-written regex is taken as intended."""

    def test_guard_skips_terms_only(self):
        event_text = "Tag Heuer Spanish Grand Prix | Spanish GP | Spain"
        terms = [kw("Spanish", "Spanish")]
        regex = [kw("Spanish", stream_pattern="spanish")]
        assert check_exception_keyword("Spanish GP Race", terms, event_text)[0] is None
        assert check_exception_keyword("Spanish GP Race", regex, event_text)[0] == "Spanish"


class TestExistingCallersUnchanged:
    def test_positional_signature(self):
        keywords = [kw("Spanish", "Spanish, (ESP)")]
        assert check_exception_keyword("Match (ESP)", keywords, None, None) == (
            "Spanish",
            "consolidate",
        )


class TestCrud:
    def test_round_trip_and_clear(self, db_conn):
        kid = create_keyword(
            db_conn,
            "ES",
            "",
            m3u_group_pattern=r"^ES\|",
            m3u_groups=[{"id": 33, "name": "ES| VIX PPV"}],
            stream_pattern=r"\(MX\)",
            streams=[{"id": 42, "name": "feed"}],
            event_group_ids=[17],
        )
        k = get_keyword(db_conn, kid)
        assert k.match_terms == ""
        assert k.m3u_group_pattern == r"^ES\|"
        assert k.m3u_group_id_set == {33}
        assert k.stream_id_set == {42}
        assert k.event_group_id_set == {17}
        assert k.streams == [{"id": 42, "name": "feed"}]

        update_keyword(db_conn, kid, m3u_group_pattern="", streams=[], event_group_ids=[])
        k = get_keyword(db_conn, kid)
        assert k.m3u_group_pattern is None
        assert k.streams == [] and k.event_group_ids == []
        # Omitted sources are left alone
        assert k.m3u_groups == [{"id": 33, "name": "ES| VIX PPV"}]
        assert k.stream_pattern == r"\(MX\)"

    def test_existing_rows_have_no_sources(self, db_conn):
        k = get_keyword(db_conn, create_keyword(db_conn, "4K", "4K, UHD"))
        assert (k.m3u_group_pattern, k.m3u_groups, k.stream_pattern, k.streams) == (
            None,
            [],
            None,
            [],
        )
        assert not k.uses_m3u_group


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.database import init_db

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    return TestClient(app)


class TestApi:
    def test_create_source_only(self, api):
        r = api.post(
            "/api/v1/keywords",
            json={
                "label": "ES",
                "m3u_group_pattern": r"^ES\|",
                "m3u_groups": [{"id": 3, "name": "ES| A"}],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["match_terms"] == "" and body["match_term_list"] == []
        assert body["m3u_groups"] == [{"id": 3, "name": "ES| A"}]
        assert body["streams"] == [] and body["event_group_ids"] == []

    def test_create_needs_a_source(self, api):
        r = api.post("/api/v1/keywords", json={"label": "ES", "match_terms": "  "})
        assert r.status_code == 400

    @pytest.mark.parametrize("field", ["m3u_group_pattern", "stream_pattern"])
    def test_invalid_regex_is_400(self, api, field):
        r = api.post(
            "/api/v1/keywords", json={"label": "ES", "match_terms": "x", field: "(unclosed"}
        )
        assert r.status_code == 400
        assert "Invalid regular expression" in r.json()["detail"]

    def test_update_clears_terms_when_sources_remain(self, api):
        kid = api.post(
            "/api/v1/keywords",
            json={"label": "ES", "match_terms": "Spanish", "event_group_ids": [4]},
        ).json()["id"]
        r = api.put(f"/api/v1/keywords/{kid}", json={"match_terms": ""})
        assert r.status_code == 200, r.text
        assert r.json()["match_terms"] == ""

        # ...but not the last source as well
        r = api.put(f"/api/v1/keywords/{kid}", json={"event_group_ids": []})
        assert r.status_code == 400
        assert api.get(f"/api/v1/keywords/{kid}").json()["event_group_ids"] == [4]

    def test_list_includes_sources(self, api):
        api.post("/api/v1/keywords", json={"label": "ES", "stream_pattern": r"\(MX\)"})
        rows = {k["label"]: k for k in api.get("/api/v1/keywords").json()["keywords"]}
        assert rows["ES"]["stream_pattern"] == r"\(MX\)"
        assert rows["Spanish"]["stream_pattern"] is None  # seeded default


def _channel(conn, event_id, keyword):
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=None,
        event_id=event_id,
        event_provider="espn",
        tvg_id=f"tvg-{event_id}-{keyword or 'main'}",
        channel_name=f"{event_id} {keyword or 'main'}",
        exception_keyword=keyword,
    )


class TestEnforcer:
    def _setup(self, conn, *, on_keyword, m3u_group_id, m3u_group_name, pattern=r"^ES\|"):
        create_keyword(conn, "ZZES", "", m3u_group_pattern=pattern)
        main_id = _channel(conn, "evt-1", None)
        es_id = _channel(conn, "evt-1", "ZZES")
        add_stream_to_channel(
            conn=conn,
            managed_channel_id=es_id if on_keyword else main_id,
            dispatcharr_stream_id=42,
            stream_name="Arsenal v Chelsea",
            priority=0,
            m3u_group_id=m3u_group_id,
            m3u_group_name=m3u_group_name,
        )
        conn.commit()
        return main_id, es_id

    def test_group_tagged_stream_stays(self, db_factory):
        with db_factory() as conn:
            main_id, es_id = self._setup(
                conn, on_keyword=True, m3u_group_id=33, m3u_group_name="ES| DAZN"
            )
        result = KeywordEnforcer(db_factory=db_factory).enforce()
        assert not result.streams_moved
        with db_factory() as conn:
            assert [s.dispatcharr_stream_id for s in get_channel_streams(conn, es_id)] == [42]

    def test_group_evidence_moves_stream_to_keyword(self, db_factory):
        with db_factory() as conn:
            main_id, es_id = self._setup(
                conn, on_keyword=False, m3u_group_id=33, m3u_group_name="ES| DAZN"
            )
        result = KeywordEnforcer(db_factory=db_factory).enforce()
        assert result.streams_moved
        with db_factory() as conn:
            moved = get_channel_streams(conn, es_id)
            assert [s.dispatcharr_stream_id for s in moved] == [42]
            # carried across the move
            assert (moved[0].m3u_group_id, moved[0].m3u_group_name) == (33, "ES| DAZN")

    def test_pre_upgrade_row_is_not_moved(self, db_factory):
        # Attached before the M3U group was stored: the keyword can't be
        # re-confirmed from the row, so the stream stays until backfilled.
        with db_factory() as conn:
            main_id, es_id = self._setup(
                conn, on_keyword=True, m3u_group_id=None, m3u_group_name=None
            )
        result = KeywordEnforcer(db_factory=db_factory).enforce()
        assert not result.streams_moved
        with db_factory() as conn:
            assert len(get_channel_streams(conn, es_id)) == 1

    def test_backfilled_row_with_other_group_moves_back(self, db_factory):
        with db_factory() as conn:
            main_id, es_id = self._setup(
                conn, on_keyword=True, m3u_group_id=None, m3u_group_name=None
            )
            assert update_stream_m3u_group(conn, es_id, 42, 77, "UK| SPORT")
            assert not update_stream_m3u_group(conn, es_id, 42, 77, "UK| SPORT")
            conn.commit()
        result = KeywordEnforcer(db_factory=db_factory).enforce()
        assert result.streams_moved
        with db_factory() as conn:
            assert [s.dispatcharr_stream_id for s in get_channel_streams(conn, main_id)] == [42]


class TestStreamGroup:
    def test_dispatcharr_puts_the_id_in_channel_group(self):
        stream = SimpleNamespace(channel_group=33, channel_group_id=None)
        assert stream_m3u_group(stream, {33: "ES| VIX PPV"}) == (33, "ES| VIX PPV")

    def test_channel_group_id_preferred(self):
        stream = SimpleNamespace(channel_group=None, channel_group_id=5)
        assert stream_m3u_group(stream, {}) == (5, None)

    @pytest.mark.parametrize(
        "stream", [None, SimpleNamespace(channel_group="ES|", channel_group_id=None)]
    )
    def test_unknown(self, stream):
        assert stream_m3u_group(stream, {1: "x"}) == (None, None)


class TestLifecycleCheck:
    """The creator's keyword check reads the stream dict and the event group."""

    def test_service_passes_sources(self, db_factory):
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        with db_factory() as conn:
            create_keyword(conn, "ZZES", "", m3u_group_pattern=r"^ES\|")
            create_keyword(conn, "ZZEG", "", event_group_ids=[16])
            svc = ChannelLifecycleService(
                db_factory=db_factory,
                sports_service=MagicMock(),
                channel_manager=MagicMock(),
                logo_manager=MagicMock(),
                epg_manager=MagicMock(),
            )
            stream = {"id": 1, "m3u_group_id": 33, "m3u_group_name": "ES| DAZN PPV"}
            assert (
                svc._check_exception_keyword("Arsenal v Chelsea", conn, stream=stream)[0] == "ZZES"
            )
            svc._exception_keywords = None
            assert (
                svc._check_exception_keyword("Arsenal v Chelsea", conn, event_group_id=16)[0]
                == "ZZEG"
            )
            assert svc._check_exception_keyword("Arsenal v Chelsea", conn)[0] is None
