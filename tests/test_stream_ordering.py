"""Tests for StreamOrderingService.

Covers the rule-matching engine, with focus on the regex-heavy additions from
PR #216 (team_feed / not_team_feed feed detection, the stream_type team filter,
and the catch_all fallback rule), plus the team-term builder and key parsing.
"""

import pytest

from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.connection import get_connection, get_db, init_db
from teamarr.database.settings.types import StreamOrderingRule
from teamarr.services.stream_ordering import (
    NO_MATCH_PRIORITY,
    StreamOrderingService,
)


def _stream(name: str | None = None, match_type: str = "event") -> ManagedChannelStream:
    return ManagedChannelStream(
        id=1,
        managed_channel_id=1,
        dispatcharr_stream_id=1,
        stream_name=name,
        match_type=match_type,
    )


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Fresh DB seeded with a few teams in team_cache and the teams table."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    init_db()
    with get_db() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_cache
            (team_name, team_abbrev, team_short_name, provider, provider_team_id, league, sport)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Pittsburgh Pirates", "PIT", "Pirates", "espn", "23", "mlb", "baseball"),
                ("Chicago Cubs", "CHC", "Cubs", "espn", "16", "mlb", "baseball"),
                ("Cincinnati Reds", "CIN", "Reds", "espn", "17", "mlb", "baseball"),
            ],
        )
        conn.commit()

    conn = get_connection()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Existing rule types still work
# ---------------------------------------------------------------------------


class TestBasicRules:
    def test_regex_match(self):
        svc = StreamOrderingService([StreamOrderingRule("regex", r"(?i)1080p", 1)])
        assert svc.compute_priority(_stream("ESPN 1080p")) == 1
        assert svc.compute_priority(_stream("ESPN 720p")) == NO_MATCH_PRIORITY

    def test_m3u_match_case_insensitive(self):
        svc = StreamOrderingService([StreamOrderingRule("m3u", "Premium IPTV", 1)])
        s = _stream("anything")
        s.m3u_account_name = "premium iptv"
        assert svc.compute_priority(s) == 1

    def test_first_match_wins_by_priority(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)1080p", 5),
            StreamOrderingRule("regex", r"(?i)espn", 2),
        ]
        svc = StreamOrderingService(rules)
        # ESPN rule has lower number → evaluated first → wins
        assert svc.compute_priority(_stream("ESPN 1080p")) == 2


# ---------------------------------------------------------------------------
# epg_match rule (epic 183 — EPG program-data matched streams)
# ---------------------------------------------------------------------------


class TestEPGMatch:
    def _epg_stream(self, match_method):
        return ManagedChannelStream(
            id=1, managed_channel_id=1, dispatcharr_stream_id=1,
            stream_name="ESPN", match_method=match_method,
        )

    def test_epg_match_matches_epg_method(self):
        svc = StreamOrderingService([StreamOrderingRule("epg_match", "", 1)])
        assert svc.compute_priority(self._epg_stream("epg")) == 1

    def test_epg_match_ignores_other_methods(self):
        svc = StreamOrderingService([StreamOrderingRule("epg_match", "", 1)])
        assert svc.compute_priority(self._epg_stream("fuzzy")) == NO_MATCH_PRIORITY
        assert svc.compute_priority(self._epg_stream(None)) == NO_MATCH_PRIORITY

    def test_epg_match_with_catch_all_fallback(self):
        rules = [
            StreamOrderingRule("epg_match", "", 1),
            StreamOrderingRule("catch_all", "", 50),
        ]
        svc = StreamOrderingService(rules)
        assert svc.compute_priority(self._epg_stream("epg")) == 1
        assert svc.compute_priority(self._epg_stream("fuzzy")) == 50


class TestDispatcharrGroup:
    def _stream(self, dp_group):
        return ManagedChannelStream(
            id=1, managed_channel_id=1, dispatcharr_stream_id=1,
            stream_name="ESPN", dispatcharr_channel_group=dp_group,
        )

    def test_matches_dispatcharr_group_case_insensitive(self):
        svc = StreamOrderingService([StreamOrderingRule("dispatcharr_group", "US Sports", 1)])
        assert svc.compute_priority(self._stream("us sports")) == 1

    def test_ignores_other_group(self):
        svc = StreamOrderingService([StreamOrderingRule("dispatcharr_group", "US Sports", 1)])
        assert svc.compute_priority(self._stream("UK Sports")) == NO_MATCH_PRIORITY

    def test_non_channel_source_stream_never_matches(self):
        # Streams without a DP channel group (normal M3U-matched streams) never match.
        svc = StreamOrderingService([StreamOrderingRule("dispatcharr_group", "US Sports", 1)])
        assert svc.compute_priority(self._stream(None)) == NO_MATCH_PRIORITY


# ---------------------------------------------------------------------------
# catch_all fallback
# ---------------------------------------------------------------------------


class TestCatchAll:
    def test_catch_all_sets_fallback_priority(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)1080p", 1),
            StreamOrderingRule("catch_all", "", 50),
        ]
        svc = StreamOrderingService(rules)
        assert svc.compute_priority(_stream("ESPN 1080p")) == 1  # matched rule wins
        assert svc.compute_priority(_stream("ESPN 720p")) == 50  # falls to catch_all

    def test_catch_all_does_not_act_as_matcher(self):
        # A catch_all earlier in priority order must not short-circuit real rules.
        rules = [
            StreamOrderingRule("catch_all", "", 2),
            StreamOrderingRule("regex", r"(?i)espn", 5),
        ]
        svc = StreamOrderingService(rules)
        # ESPN stream matches the regex (prio 5), not the catch_all (prio 2)
        result = svc.compute_priority_with_details(_stream("ESPN HD"))
        assert result.matched_rule_type == "regex"
        assert result.computed_priority == 5

    def test_no_catch_all_uses_no_match_priority(self):
        svc = StreamOrderingService([StreamOrderingRule("regex", r"(?i)zzz", 1)])
        result = svc.compute_priority_with_details(_stream("ESPN HD"))
        assert result.computed_priority == NO_MATCH_PRIORITY
        assert result.matched_rule_type is None


# ---------------------------------------------------------------------------
# Team-term builder (+ stopword guard)
# ---------------------------------------------------------------------------


class TestBuildTeamTerms:
    def test_extracts_words_city_and_abbrev(self):
        svc = StreamOrderingService([])
        rows = [{"team_name": "Pittsburgh Pirates", "team_abbrev": "PIT"}]
        terms = {t.replace("\\", "") for t in svc._build_team_terms(rows)}
        assert terms == {"Pittsburgh", "Pirates", "PIT"}

    def test_multiword_city_term(self):
        svc = StreamOrderingService([])
        rows = [{"team_name": "New York Yankees", "team_abbrev": "NYY"}]
        terms = {t.replace("\\", "") for t in svc._build_team_terms(rows)}
        # "New" is dropped (<3? no, 3 chars) — actually kept; city = "New York"
        assert "New York" in terms
        assert "Yankees" in terms
        assert "NYY" in terms

    def test_short_words_excluded(self):
        svc = StreamOrderingService([])
        rows = [{"team_name": "FC Bayern", "team_abbrev": "B"}]
        terms = {t.replace("\\", "") for t in svc._build_team_terms(rows)}
        # "FC" (2 chars) excluded as word; "B" (1 char) excluded as abbrev
        assert "Bayern" in terms
        assert "FC" not in terms
        assert "B" not in terms

    def test_stopwords_dropped(self):
        svc = StreamOrderingService([])
        rows = [{"team_name": "The Strongest", "team_abbrev": "STR"}]
        terms = {t.replace("\\", "") for t in svc._build_team_terms(rows)}
        assert "the" not in {t.lower() for t in terms}
        assert "Strongest" in terms


# ---------------------------------------------------------------------------
# team_feed / not_team_feed
# ---------------------------------------------------------------------------


class TestTeamFeed:
    KEY = "espn:mlb:23"  # Pittsburgh Pirates

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Cubs vs Pirates (Home)", True),
            ("Pirates vs Cubs (Away)", True),
            ("Pirates @ Cubs Away", True),
            ("(Pirates feed) MLB", True),
            ("Home Feed: Cubs vs Pirates", True),
            ("Away Feed: Pirates vs Cubs", True),
            ("Pirates vs Cubs", False),  # no directional marker
            ("Cubs vs Reds (Home)", False),  # different team's feed
            ("ESPN National Feed", False),  # generic, no team
        ],
    )
    def test_team_feed_matching(self, seeded_db, name, expected):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        assert svc.compute_priority(_stream(name)) == (1 if expected else NO_MATCH_PRIORITY)

    def test_not_team_feed_inverts_only_feed_marked_streams(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("not_team_feed", self.KEY, 1)], seeded_db)
        # Feed-marked, NOT pirates → matches
        assert svc.compute_priority(_stream("Cubs vs Reds (Home)")) == 1
        # Pirates' own feed → does NOT match
        assert svc.compute_priority(_stream("Pirates vs Cubs (Away)")) == NO_MATCH_PRIORITY
        # No feed marker at all → gated out, does NOT match
        assert svc.compute_priority(_stream("Generic National stream")) == NO_MATCH_PRIORITY

    def test_empty_value_is_noop(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "", 1)], seeded_db)
        assert svc.compute_priority(_stream("Pirates vs Cubs (Away)")) == NO_MATCH_PRIORITY

    def test_legacy_integer_id_path(self, seeded_db):
        # The teams table is seeded with demo teams; id=4 is the Detroit Tigers.
        # The legacy team_feed path resolves integer IDs against the teams table.
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "4", 1)], seeded_db)
        assert svc.compute_priority(_stream("Cubs vs Tigers (Home)")) == 1
        assert svc.compute_priority(_stream("Cubs vs Pirates (Home)")) == NO_MATCH_PRIORITY

    def test_pattern_is_cached(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        svc.compute_priority(_stream("Cubs vs Pirates (Home)"))
        assert self.KEY in svc._team_feed_patterns

    def test_no_connection_degrades_gracefully(self):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "espn:mlb:23", 1)], conn=None)
        assert svc.compute_priority(_stream("Cubs vs Pirates (Home)")) == NO_MATCH_PRIORITY


# ---------------------------------------------------------------------------
# stream_type with optional team filter
# ---------------------------------------------------------------------------


class TestStreamTypeFilter:
    def test_plain_stream_type_no_filter(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("stream_type", "team", 1)], seeded_db)
        assert svc.compute_priority(_stream("anything", match_type="team")) == 1
        assert svc.compute_priority(_stream("anything", match_type="event")) == NO_MATCH_PRIORITY

    def test_team_filter_narrows_to_selected_team(self, seeded_db):
        rule = StreamOrderingRule("stream_type", "team|espn:mlb:23", 1)
        svc = StreamOrderingService([rule], seeded_db)
        # team-type stream naming the Pirates → matches
        assert svc.compute_priority(_stream("Pirates Network", match_type="team")) == 1
        # team-type stream naming a different team → no match
        assert svc.compute_priority(_stream("Cubs Network", match_type="team")) == NO_MATCH_PRIORITY

    def test_team_filter_requires_correct_stream_type(self, seeded_db):
        rule = StreamOrderingRule("stream_type", "team|espn:mlb:23", 1)
        svc = StreamOrderingService([rule], seeded_db)
        # right team name but event-type → stream_type mismatch
        s = _stream("Pirates Network", match_type="event")
        assert svc.compute_priority(s) == NO_MATCH_PRIORITY

    def test_empty_team_filter_matches_all_team_streams(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("stream_type", "team|", 1)], seeded_db)
        assert svc.compute_priority(_stream("Cubs Network", match_type="team")) == 1


# ---------------------------------------------------------------------------
# Key parsing (2-part vs 3-part)
# ---------------------------------------------------------------------------


class TestKeyParsing:
    def test_two_part_legacy_key(self, seeded_db):
        svc = StreamOrderingService([], seeded_db)
        rows = svc._query_team_cache_by_keys(["espn:23"])
        names = {r["team_name"] for r in rows}
        assert "Pittsburgh Pirates" in names

    def test_three_part_key(self, seeded_db):
        svc = StreamOrderingService([], seeded_db)
        rows = svc._query_team_cache_by_keys(["espn:mlb:23"])
        names = {r["team_name"] for r in rows}
        assert "Pittsburgh Pirates" in names

    def test_mixed_keys(self, seeded_db):
        svc = StreamOrderingService([], seeded_db)
        rows = svc._query_team_cache_by_keys(["espn:23", "espn:mlb:16"])
        names = {r["team_name"] for r in rows}
        assert {"Pittsburgh Pirates", "Chicago Cubs"} <= names
