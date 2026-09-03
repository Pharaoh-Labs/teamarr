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
    BAND_STRIDE,
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
        # One followed team for the legacy integer-id team_feed path.
        conn.execute(
            """
            INSERT INTO teams
            (provider, provider_team_id, primary_league, sport,
             team_name, team_abbrev, channel_id)
            VALUES ('espn', '8', 'mlb', 'baseball',
                    'Detroit Tigers', 'DET', 'test.tigers')
            """
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

    def test_stream_type_excludes_epg_matched_streams(self):
        # Event/team/EPG are one mutually-exclusive Stream Type select in the
        # UI — an EPG-matched stream must never fall into an event or team
        # band (#448).
        svc = StreamOrderingService([StreamOrderingRule("stream_type", "event", 1)])
        assert svc.compute_priority(self._epg_stream("epg")) == NO_MATCH_PRIORITY

        team_epg = ManagedChannelStream(
            id=1, managed_channel_id=1, dispatcharr_stream_id=1,
            stream_name="ESPN", match_type="team", match_method="epg",
        )
        svc = StreamOrderingService([StreamOrderingRule("stream_type", "team", 1)])
        assert svc.compute_priority(team_epg) == NO_MATCH_PRIORITY

    def test_event_rule_above_epg_rule_does_not_capture_epg_streams(self):
        # The #448 repro: rules prioritizing event matches above EPG matches.
        # EPG-matched streams must land in the EPG band, name matches in the
        # event band.
        rules = [
            StreamOrderingRule("stream_type", "event", 1),
            StreamOrderingRule("epg_match", "", 2),
        ]
        svc = StreamOrderingService(rules)
        assert svc.compute_priority(self._epg_stream("epg")) == 2
        assert svc.compute_priority(self._epg_stream("fuzzy")) == 1
        assert svc.compute_priority(self._epg_stream(None)) == 1


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
        # The legacy team_feed path resolves integer IDs against the teams table.
        tigers_id = seeded_db.execute(
            "SELECT id FROM teams WHERE team_abbrev = 'DET'"
        ).fetchone()[0]
        svc = StreamOrderingService(
            [StreamOrderingRule("team_feed", str(tigers_id), 1)], seeded_db
        )
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


class TestStatsMetric:
    """The stats_metric rule matches streams by Dispatcharr stream_stats values."""

    def _stream(self, stats: dict | None) -> ManagedChannelStream:
        return ManagedChannelStream(
            id=1, managed_channel_id=1, dispatcharr_stream_id=1, stream_stats=stats
        )

    def _svc(self, value: str) -> StreamOrderingService:
        return StreamOrderingService([StreamOrderingRule("stats_metric", value, 1)])

    @pytest.mark.parametrize(
        "operator,threshold,bitrate,expected",
        [
            (">=", "4000", 4000, True),
            (">=", "4000", 3999, False),
            ("<=", "4000", 4000, True),
            ("<=", "4000", 4001, False),
            (">", "4000", 4001, True),
            (">", "4000", 4000, False),
            ("<", "4000", 3999, True),
            ("<", "4000", 4000, False),
            ("=", "4000", 4000, True),
            ("=", "4000", 4001, False),
        ],
    )
    def test_operators(self, operator, threshold, bitrate, expected):
        svc = self._svc(f"ffmpeg_output_bitrate|{operator}|{threshold}")
        stream = self._stream({"ffmpeg_output_bitrate": bitrate})
        matched = svc.compute_priority(stream) == 1
        assert matched is expected

    def test_virtual_resolution_width_and_height(self):
        stream = self._stream({"resolution": "1920x1080"})
        assert self._svc("resolution_width|>=|1920").compute_priority(stream) == 1
        assert self._svc("resolution_height|>=|1080").compute_priority(stream) == 1
        assert self._svc("resolution_width|>|1920").compute_priority(stream) == NO_MATCH_PRIORITY

    def test_malformed_resolution_does_not_match(self):
        stream = self._stream({"resolution": "1080"})  # no "x"
        assert self._svc("resolution_width|>=|720").compute_priority(stream) == NO_MATCH_PRIORITY

    def test_multi_condition_and(self):
        rule = "source_fps|>=|50;ffmpeg_output_bitrate|>=|4000"
        both = self._stream({"source_fps": 60, "ffmpeg_output_bitrate": 5000})
        one = self._stream({"source_fps": 30, "ffmpeg_output_bitrate": 5000})
        assert self._svc(rule).compute_priority(both) == 1
        assert self._svc(rule).compute_priority(one) == NO_MATCH_PRIORITY

    def test_is_unknown_matches_when_absent(self):
        # No stats at all, or the specific metric missing → is_unknown matches.
        assert self._svc("source_fps|is_unknown").compute_priority(self._stream(None)) == 1
        assert (
            self._svc("source_fps|is_unknown").compute_priority(
                self._stream({"resolution": "1920x1080"})
            )
            == 1
        )
        # Metric present → is_unknown does not match.
        assert (
            self._svc("source_fps|is_unknown").compute_priority(self._stream({"source_fps": 60}))
            == NO_MATCH_PRIORITY
        )

    def test_numeric_op_with_no_stats_does_not_match(self):
        svc = self._svc("source_fps|>=|50")
        assert svc.compute_priority(self._stream(None)) == NO_MATCH_PRIORITY

    def test_malformed_rule_value_does_not_raise(self):
        stream = self._stream({"source_fps": 60})
        assert self._svc("").compute_priority(stream) == NO_MATCH_PRIORITY
        # no operator
        assert self._svc("source_fps").compute_priority(stream) == NO_MATCH_PRIORITY
        assert self._svc("source_fps|>=|notanumber").compute_priority(stream) == NO_MATCH_PRIORITY


class TestEvaluateRules:
    """evaluate_rules reports every matching rule plus the 'everything else'
    baseline, flagging the one that won."""

    def test_multiple_matches_only_lowest_priority_wins(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)1080p", 5),
            StreamOrderingRule("regex", r"(?i)espn", 2),
        ]
        svc = StreamOrderingService(rules)
        evals = svc.evaluate_rules(_stream("ESPN 1080p"))

        # Two regex matches + the implicit baseline (no catch_all configured).
        assert [e.type for e in evals] == ["regex", "regex", "catch_all"]
        winners = [e for e in evals if e.is_winner]
        assert len(winners) == 1
        # The priority-2 ESPN rule wins (lower number, evaluated first).
        assert winners[0].priority == 2
        assert winners[0].type == "regex"

    def test_baseline_shown_with_default_priority_when_no_catch_all(self):
        svc = StreamOrderingService([StreamOrderingRule("regex", r"(?i)espn", 2)])
        baseline = svc.evaluate_rules(_stream("ESPN 1080p"))[-1]
        assert baseline.type == "catch_all"
        assert baseline.priority == NO_MATCH_PRIORITY
        assert baseline.is_winner is False  # a specific rule won

    def test_catch_all_wins_when_nothing_else_matches(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)1080p", 5),
            StreamOrderingRule("catch_all", "", 50),
        ]
        svc = StreamOrderingService(rules)
        evals = svc.evaluate_rules(_stream("ESPN 720p"))

        assert len(evals) == 1
        assert evals[0].type == "catch_all"
        assert evals[0].priority == 50
        assert evals[0].is_winner is True

    def test_catch_all_shown_as_baseline_when_a_rule_matches(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)1080p", 5),
            StreamOrderingRule("catch_all", "", 50),
        ]
        svc = StreamOrderingService(rules)
        evals = svc.evaluate_rules(_stream("ESPN 1080p"))

        assert [e.type for e in evals] == ["regex", "catch_all"]
        assert evals[0].is_winner is True  # the regex rule won
        assert evals[1].is_winner is False  # baseline shown but did not win
        assert evals[1].priority == 50

    def test_no_rules_returns_just_the_baseline(self):
        evals = StreamOrderingService([]).evaluate_rules(_stream("anything"))
        assert len(evals) == 1
        assert evals[0].type == "catch_all"
        assert evals[0].priority == NO_MATCH_PRIORITY
        assert evals[0].is_winner is True


# ---------------------------------------------------------------------------
# Additive scoring + hard-precedence escape hatch (epic teamarr-5ag)
# ---------------------------------------------------------------------------


def _m3u_stream(name: str, account: str, sid: int = 1):
    s = _stream(name)
    s.m3u_account_name = account
    s.id = sid
    return s


class TestAdditiveScoring:
    def test_scores_sum_within_baseline_band(self):
        rules = [
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
            StreamOrderingRule("regex", r"(?i)EPG", 99, mode="score", points=10),
        ]
        svc = StreamOrderingService(rules)
        both = svc.compute_priority(_stream("Foo 4K EPG"))
        only_4k = svc.compute_priority(_stream("Foo 4K"))
        only_epg = svc.compute_priority(_stream("Foo EPG"))
        neither = svc.compute_priority(_stream("Foo"))
        # Higher total score → lower (earlier) priority int
        assert both < only_4k < neither
        assert both < only_epg < neither
        assert only_4k < only_epg  # 25 beats 10

    def test_exact_collapse_formula(self):
        svc = StreamOrderingService(
            [StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25)]
        )
        assert svc.compute_priority(_stream("x 4K")) == 999 * BAND_STRIDE - 25
        assert svc.compute_priority(_stream("x")) == 999 * BAND_STRIDE

    def test_hard_band_dominates_score(self):
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
        ]
        svc = StreamOrderingService(rules)
        a_sd = _m3u_stream("Game SD", "ProviderA")  # band 1, score 0
        b_4k = _stream("Game 4K")  # baseline band, score +25
        assert svc.compute_priority(a_sd) < svc.compute_priority(b_4k)

    def test_score_orders_within_same_band(self):
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
        ]
        svc = StreamOrderingService(rules)
        hd = _m3u_stream("Game HD", "ProviderA")
        uhd = _m3u_stream("Game 4K", "ProviderA")
        assert svc.compute_priority(uhd) < svc.compute_priority(hd)

    def test_band1_positive_score_collapses_below_stride(self):
        # Invariant the UI decode (ManagedChannelsTable.decodePriority) must respect:
        # a band-1 stream with a positive score collapses to just under BAND_STRIDE
        # (e.g. 999_975 for +25), NOT above it. The decode must split scored vs.
        # legacy values on NO_MATCH_PRIORITY, not on BAND_STRIDE, or it renders the
        # raw collapsed int instead of "1 +25".
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
        ]
        svc = StreamOrderingService(rules)
        collapsed = svc.compute_priority(_m3u_stream("Game 4K", "ProviderA"))
        assert collapsed == 1 * BAND_STRIDE - 25  # 999_975
        assert NO_MATCH_PRIORITY < collapsed < BAND_STRIDE

    def test_negative_points_demote_below_baseline(self):
        svc = StreamOrderingService(
            [StreamOrderingRule("regex", r"(?i)SD", 99, mode="score", points=-50)]
        )
        assert svc.compute_priority(_stream("Game SD")) > svc.compute_priority(_stream("Game"))

    def test_score_clamped_to_keep_bands_hard(self):
        # An absurd score must never lift a worse band above a better one.
        huge = BAND_STRIDE * 5
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("m3u", "ProviderB", 2, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=huge),
        ]
        svc = StreamOrderingService(rules)
        a = _m3u_stream("Game SD", "ProviderA")  # band 1, score 0
        b = _m3u_stream("Game 4K", "ProviderB")  # band 2, clamped huge score
        assert svc.compute_priority(a) < svc.compute_priority(b)

    def test_sort_streams_orders_by_band_then_score(self):
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
            StreamOrderingRule("regex", r"(?i)SD", 99, mode="score", points=-50),
        ]
        svc = StreamOrderingService(rules)
        a_hd = _m3u_stream("A HD", "ProviderA", sid=1)  # band 1, 0
        a_4k = _m3u_stream("A 4K", "ProviderA", sid=2)  # band 1, +25
        b_4k = _stream("B 4K")  # baseline, +25
        b_4k.id = 3
        b_sd = _stream("B SD")  # baseline, -50
        b_sd.id = 4
        ordered = svc.sort_streams([a_hd, b_sd, b_4k, a_4k])
        assert [s.id for s in ordered] == [2, 1, 3, 4]

    def test_evaluate_rules_reports_score_contributors(self):
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 1, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
        ]
        svc = StreamOrderingService(rules)
        evals = svc.evaluate_rules(_m3u_stream("Game 4K", "ProviderA"))
        winners = [e for e in evals if e.is_winner]
        assert len(winners) == 1
        assert winners[0].type == "m3u" and winners[0].mode == "priority"
        score_entries = [e for e in evals if e.mode == "score"]
        assert len(score_entries) == 1
        assert score_entries[0].points == 25
        assert score_entries[0].is_winner is False

    def test_attach_time_compute_honors_epg_and_dp_group_fields(self, seeded_db):
        """compute_stream_priority_from_rules must apply dispatcharr_group /
        epg_match / stream_type rules at attach time (#379).

        Before the fix the helper's stub stream carried only name/account/group,
        so these rule types silently never matched and the order pushed to
        Dispatcharr at attach was wrong until the end-of-run reorder pass.
        """
        from teamarr.database.channels import compute_stream_priority_from_rules
        from teamarr.database.settings.update import update_stream_ordering_rules

        update_stream_ordering_rules(
            seeded_db,
            [
                {"type": "dispatcharr_group", "value": "Sports CA", "priority": 99,
                 "mode": "score", "points": 800},
                {"type": "epg_match", "value": "", "priority": 99,
                 "mode": "score", "points": 10},
                {"type": "stream_type", "value": "team", "priority": 99,
                 "mode": "score", "points": -50},
            ],
        )
        seeded_db.commit()

        epg_in_group = compute_stream_priority_from_rules(
            seeded_db, "TSN4", None, None,
            match_method="epg", dispatcharr_channel_group="Sports CA",
        )
        assert epg_in_group == NO_MATCH_PRIORITY * BAND_STRIDE - 810

        team_stream = compute_stream_priority_from_rules(
            seeded_db, "Pirates 24/7", None, None, match_type="team",
        )
        assert team_stream == NO_MATCH_PRIORITY * BAND_STRIDE + 50

        plain = compute_stream_priority_from_rules(seeded_db, "ESPN", None, None)
        assert plain == NO_MATCH_PRIORITY * BAND_STRIDE

    def test_details_expose_band_and_score(self):
        rules = [
            StreamOrderingRule("m3u", "ProviderA", 3, mode="priority"),
            StreamOrderingRule("regex", r"(?i)4K", 99, mode="score", points=25),
        ]
        svc = StreamOrderingService(rules)
        d = svc.compute_priority_with_details(_m3u_stream("Game 4K", "ProviderA"))
        assert d.band == 3
        assert d.score == 25
        assert d.matched_rule_type == "m3u"
        assert d.computed_priority == 3 * BAND_STRIDE - 25


# ---------------------------------------------------------------------------
# team_feed / not_team_feed against the persisted feed_team_id (#489)
# ---------------------------------------------------------------------------


def _feed_stream(
    name: str | None = None,
    feed_team_id: str | None = None,
    match_type: str = "event",
) -> ManagedChannelStream:
    return ManagedChannelStream(
        id=1,
        managed_channel_id=1,
        dispatcharr_stream_id=1,
        stream_name=name,
        feed_team_id=feed_team_id,
        match_type=match_type,
    )


class TestTeamFeedResolved:
    """Resolved feed_team_id is authoritative; the name regex is the fallback."""

    KEY = "espn:mlb:23"  # Pittsburgh Pirates

    def test_resolved_feed_matches_without_name_signal(self, seeded_db):
        # 'Pirates.TV' carries no vs/home/away marker — the regex can't see it,
        # but the matching layer resolved it, so the rule fires (#489).
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        assert svc.compute_priority(_feed_stream("Pirates.TV", feed_team_id="23")) == 1

    def test_resolved_other_team_does_not_match(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        assert (
            svc.compute_priority(_feed_stream("Cubs.TV", feed_team_id="16"))
            == NO_MATCH_PRIORITY
        )

    def test_resolution_is_authoritative_over_name(self, seeded_db):
        # Resolved to the Cubs: even a name the Pirates regex would match
        # must not fire the Pirates rule.
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        stream = _feed_stream("Cubs vs Pirates (Home)", feed_team_id="16")
        assert svc.compute_priority(stream) == NO_MATCH_PRIORITY

    def test_null_feed_team_falls_back_to_regex(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        assert svc.compute_priority(_feed_stream("Cubs vs Pirates (Home)")) == 1
        assert svc.compute_priority(_feed_stream("Pirates.TV")) == NO_MATCH_PRIORITY

    def test_team_stream_matched_side_counts_as_feed(self, seeded_db):
        # TEAM_ONLY streams carry their matched team the same way (#489):
        # 'sort Brewers team streams above Marlins' in a shared channel.
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], seeded_db)
        assert (
            svc.compute_priority(
                _feed_stream("MLB | Pittsburgh Pirates", feed_team_id="23", match_type="team")
            )
            == 1
        )

    def test_not_team_feed_matches_other_resolved_feed(self, seeded_db):
        svc = StreamOrderingService(
            [StreamOrderingRule("not_team_feed", self.KEY, 1)], seeded_db
        )
        # Another team's resolved feed matches — no name indicator needed.
        assert svc.compute_priority(_feed_stream("Cubs.TV", feed_team_id="16")) == 1
        # The rule team's own resolved feed does not.
        assert (
            svc.compute_priority(_feed_stream("Pirates.TV", feed_team_id="23"))
            == NO_MATCH_PRIORITY
        )

    def test_not_team_feed_null_keeps_indicator_gate(self, seeded_db):
        svc = StreamOrderingService(
            [StreamOrderingRule("not_team_feed", self.KEY, 1)], seeded_db
        )
        # Unresolved + no feed indicator → gated out (regex fallback semantics).
        assert svc.compute_priority(_feed_stream("Cubs.TV")) == NO_MATCH_PRIORITY

    def test_legacy_integer_rule_resolves_provider_team_id(self, seeded_db):
        # Legacy rule values hold teams-table row ids; the stream column holds
        # the provider team id ('8' for the seeded Tigers row).
        tigers_row_id = seeded_db.execute(
            "SELECT id FROM teams WHERE team_abbrev = 'DET'"
        ).fetchone()[0]
        svc = StreamOrderingService(
            [StreamOrderingRule("team_feed", str(tigers_row_id), 1)], seeded_db
        )
        assert svc.compute_priority(_feed_stream("Tigers.TV", feed_team_id="8")) == 1
        assert (
            svc.compute_priority(_feed_stream("Pirates.TV", feed_team_id="23"))
            == NO_MATCH_PRIORITY
        )

    def test_keyed_format_needs_no_connection(self):
        # Keyed rule values carry the provider team id directly, so resolved
        # streams keep matching even without a DB connection.
        svc = StreamOrderingService([StreamOrderingRule("team_feed", self.KEY, 1)], conn=None)
        assert svc.compute_priority(_feed_stream("Pirates.TV", feed_team_id="23")) == 1

    def test_empty_rule_value_never_matches_resolved(self, seeded_db):
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "", 1)], seeded_db)
        assert (
            svc.compute_priority(_feed_stream("Pirates.TV", feed_team_id="23"))
            == NO_MATCH_PRIORITY
        )

    def test_attach_time_priority_sees_feed_team(self, seeded_db):
        # compute_stream_priority_from_rules must thread feed_team_id into the
        # stub stream so team_feed rules apply at attach time, not only at the
        # end-of-run reorder pass (#379 pattern, #489).
        from teamarr.database.channels import compute_stream_priority_from_rules
        from teamarr.database.settings.update import update_stream_ordering_rules

        update_stream_ordering_rules(
            seeded_db, [{"type": "team_feed", "value": self.KEY, "priority": 1}]
        )
        seeded_db.commit()

        resolved = compute_stream_priority_from_rules(
            seeded_db, "Pirates.TV", None, None, feed_team_id="23"
        )
        assert resolved == 1

        unresolved = compute_stream_priority_from_rules(seeded_db, "Pirates.TV", None, None)
        assert unresolved == NO_MATCH_PRIORITY


# ---------------------------------------------------------------------------
# team_feed selection is scoped by SPORT, not bare provider id (#687)
# ---------------------------------------------------------------------------


def _channel(conn, league: str, sport: str) -> int:
    cur = conn.execute(
        "INSERT INTO managed_channels"
        " (event_id, event_provider, tvg_id, channel_name, league, sport)"
        " VALUES (?, 'espn', ?, ?, ?, ?)",
        (f"ev-{league}", f"teamarr.{league}", f"{league} channel", league, sport),
    )
    conn.commit()
    return cur.lastrowid


class TestTeamFeedSportScope:
    """ESPN reuses team ids across sports (#687): Cubs = mlb:16, Vikings =
    nfl:16. A bare-id compare let a Vikings selection give every Cubs feed
    +500. Within a sport the id is stable across competitions, so the scope
    is the sport — a Liverpool picked from eng.1 still matches in the UCL."""

    def test_cross_sport_collision_does_not_match(self, seeded_db):
        mlb = _channel(seeded_db, "mlb", "baseball")
        nfl = _channel(seeded_db, "nfl", "football")
        rule = StreamOrderingRule("team_feed", "espn:mlb:9,espn:nfl:16", 1)
        svc = StreamOrderingService([rule], seeded_db)
        cubs = _feed_stream("US: MLB CHICAGO CUBS RAW", feed_team_id="16")
        cubs.managed_channel_id = mlb
        vikings = _feed_stream("NFL Vikings feed", feed_team_id="16")
        vikings.managed_channel_id = nfl
        assert svc.compute_priority(cubs) != 1  # Cubs are not selected
        assert svc.compute_priority(vikings) == 1  # Vikings are

    def test_same_sport_other_competition_still_matches(self, seeded_db):
        ucl = _channel(seeded_db, "uefa.champions", "soccer")
        rule = StreamOrderingRule("team_feed", "espn:eng.1:364", 1)
        svc = StreamOrderingService([rule], seeded_db)
        liverpool = _feed_stream("Liverpool TV", feed_team_id="364")
        liverpool.managed_channel_id = ucl
        assert svc.compute_priority(liverpool) == 1

    def test_not_team_feed_treats_colliding_id_as_another_team(self, seeded_db):
        mlb = _channel(seeded_db, "mlb", "baseball")
        rule = StreamOrderingRule("not_team_feed", "espn:nfl:16", 1)
        svc = StreamOrderingService([rule], seeded_db)
        cubs = _feed_stream("Cubs feed", feed_team_id="16")
        cubs.managed_channel_id = mlb
        assert svc.compute_priority(cubs) == 1  # a team feed, but not the Vikings'

    def test_legacy_two_part_key_keeps_bare_id_compare(self, seeded_db):
        mlb = _channel(seeded_db, "mlb", "baseball")
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "espn:16", 1)], seeded_db)
        cubs = _feed_stream("Cubs feed", feed_team_id="16")
        cubs.managed_channel_id = mlb
        assert svc.compute_priority(cubs) == 1

    def test_unknown_channel_falls_back_to_bare_id(self, seeded_db):
        # Attach-time scoring of a stream not yet on a channel: no sport to
        # scope by, so the legacy compare applies until the reorder pass.
        svc = StreamOrderingService([StreamOrderingRule("team_feed", "espn:nfl:16", 1)], seeded_db)
        assert svc.compute_priority(_feed_stream("x", feed_team_id="16")) == 1

    def test_legacy_integer_ids_carry_sport(self, seeded_db):
        row = seeded_db.execute("SELECT id FROM teams WHERE team_abbrev = 'DET'").fetchone()
        tigers_id = row[0]
        mlb = _channel(seeded_db, "mlb", "baseball")
        nfl = _channel(seeded_db, "nfl", "football")
        svc = StreamOrderingService([StreamOrderingRule("team_feed", str(tigers_id), 1)], seeded_db)
        keys = svc._get_team_feed_ids(str(tigers_id))
        assert keys == {("baseball", "8")}
        lions = _feed_stream("Lions feed", feed_team_id="8")  # NFL Lions are also id 8
        lions.managed_channel_id = nfl
        tigers = _feed_stream("Tigers feed", feed_team_id="8")
        tigers.managed_channel_id = mlb
        assert svc.compute_priority(lions) != 1
        assert svc.compute_priority(tigers) == 1
