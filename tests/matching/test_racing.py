"""Racing pipeline tests: classification, matcher scoring, session durations.

Racing leagues are configured with ``event_type='event'`` and have no reliable
text keyword, so a stream is classified ``RACING_EVENT`` purely because the
group is racing-dominant and the stream has no team pattern. This is the
regression-prone path (cf. #157): a team-sport stream that leaks into a
racing-dominant group must NOT be hijacked as a race.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    StreamCategory,
    classify_stream,
    detect_racing_series_leagues,
    has_racing_text_evidence,
)
from teamarr.consumers.matching.racing_matcher import RacingMatchContext, RacingMatcher
from teamarr.consumers.racing_segments import (
    _is_practice_session,
    _isolate_stream_session_label,
    _parse_duration_from_name,
    _session_category_from_stream_name,
    _session_duration_hours,
    _session_in_category,
    expand_racing_segments,
)
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    DetectionKeywordService.invalidate_cache()


# ---------------------------------------------------------------------------
# Classification: genuine racing streams classify as RACING_EVENT
# ---------------------------------------------------------------------------


def test_f1_stream_classifies_racing():
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT
    assert c.event_hint  # full text carried for fuzzy matching


def test_nascar_stream_classifies_racing():
    c = classify_stream("NASCAR Cup Series - Daytona 500", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_nascar_espn_at_city_format_classifies_racing():
    # ESPN names NASCAR events "[Series] at [City]" — the "at" must not trigger
    # team extraction since "NASCAR Cup Series" is a series name, not a team abbrev.
    c = classify_stream("NASCAR Cup Series at San Diego", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_nascar_orap_at_city_format_classifies_racing():
    c = classify_stream("NASCAR O'Reilly Auto Parts Series at San Diego", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_single_word_series_at_venue_classifies_racing():
    # A single-word left part before at/@ is normally treated as a team code
    # ("SD at BAL"), but not when it's itself a racing series name (#349) —
    # "NASCAR @ Daytona" must reach the racing matcher, not TeamMatcher.
    for name in (
        "NASCAR @ Daytona",
        "NASCAR at Daytona",
        "F1 at Monaco",
        "IndyCar at Long Beach",
        "MotoGP at Mugello",
    ):
        c = classify_stream(name, league_event_type="event")
        assert c.category == StreamCategory.RACING_EVENT, name


def test_racing_only_applies_for_event_league_type():
    # Same name, but a non-racing (team) group must not route to racing.
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="team")
    assert c.category != StreamCategory.RACING_EVENT


# ---------------------------------------------------------------------------
# Classification: leaked team-sport streams in a racing-dominant group are
# NOT hijacked
# ---------------------------------------------------------------------------


def test_team_stream_with_separator_falls_through():
    # "SD at BAL" has a game separator → team matching, not racing.
    c = classify_stream("SD at BAL", league_event_type="event")
    assert c.category == StreamCategory.TEAM_VS_TEAM


def test_team_stream_with_nonracing_sport_hint_falls_through():
    # No separator, but a positive non-racing sport hint ("Ice Hockey") vetoes
    # racing classification — the #242 follow-up guard.
    c = classify_stream("NHL | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT


def test_hockey_single_team_in_racing_group_is_not_racing():
    c = classify_stream("US | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT


def test_racing_league_hints_cover_all_schema_racing_leagues():
    """_RACING_LEAGUE_HINTS is a hardcoded mirror of the racing leagues seeded in
    schema.sql (the classifier is a pure text module with no DB access). This test
    is the sync contract: add a racing league to the schema and it fails until the
    frozenset learns the new code."""
    import re
    from pathlib import Path

    from teamarr.consumers.matching.classifier import _RACING_LEAGUE_HINTS

    schema = Path("teamarr/database/schema.sql").read_text(encoding="utf-8")
    schema_racing_codes = {
        m.group(1)
        for m in re.finditer(r"^\s*\('([a-z0-9-]+)',[^)\n]*'racing'", schema, re.MULTILINE)
    }
    assert schema_racing_codes, "failed to parse racing leagues from schema.sql"
    missing = schema_racing_codes - _RACING_LEAGUE_HINTS
    assert not missing, f"racing leagues in schema.sql missing from _RACING_LEAGUE_HINTS: {missing}"


# ---------------------------------------------------------------------------
# RacingMatcher venue-country scoring (take-and-fix of PR #263)
#
# venue.country is deliberately NOT a peer fuzzy candidate: token_set_ratio
# scores a bare country subset at 100, so a country hit must never outrank a
# real name/circuit match on a different event. It contributes only:
# - to the single-covering-event sanity check (no ambiguity to create), and
# - as a fallback when it identifies exactly ONE covering event.
# ---------------------------------------------------------------------------


def _event(eid, name, circuit=None, country=None):
    return SimpleNamespace(
        id=eid,
        name=name,
        short_name=name,
        circuit_name=circuit,
        venue=SimpleNamespace(country=country) if country else None,
        league="nascar-cup",
    )


def _ctx(stream_name):
    return RacingMatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 14),
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=None,
    )


def _matcher():
    return RacingMatcher(service=None, cache=None)


def test_name_match_beats_country_on_other_event():
    # Doubleheader window: the stream names race A; race B shares no name tokens
    # but its venue country appears in the stream. A must win.
    a = _event("a", "Viva Mexico 250", circuit="Autodromo Hermanos Rodriguez", country="Mexico")
    b = _event("b", "Firekeepers Casino 400", circuit="Michigan Intl Speedway", country="USA")
    out = _matcher()._match_to_event(_ctx("NASCAR Cup: Viva Mexico 250"), [a, b], "nascar-cup")
    assert out.is_matched and out.event.id == "a"


def test_unique_country_fallback_matches():
    # "at Mexico City" carries no event-name tokens, but only one covering
    # event is in Mexico → country fallback resolves it.
    a = _event("a", "Viva Mexico 250", country="Mexico")
    b = _event("b", "Firekeepers Casino 400", country="USA")
    out = _matcher()._match_to_event(
        _ctx("NASCAR Cup Series at Mexico"), [a, b], "nascar-cup"
    )
    assert out.is_matched and out.event.id == "a"


def test_ambiguous_country_does_not_match():
    # Two covering events in the same country: a bare country reference must
    # stay unmatched rather than guess.
    a = _event("a", "Race One GP", country="USA")
    b = _event("b", "Race Two GP", country="USA")
    out = _matcher()._match_to_event(_ctx("Cup Series live from USA"), [a, b], "nascar-cup")
    assert not out.is_matched


def test_single_event_country_passes_sanity_check():
    # One covering event whose name shares nothing with the stream, but the
    # stream names the venue country → sanity check passes via country score.
    a = _event("a", "Viva 250", country="Mexico")
    out = _matcher()._match_to_event(_ctx("NASCAR at Mexico"), [a], "nascar-cup")
    assert out.is_matched and out.event.id == "a"


# ---------------------------------------------------------------------------
# Racing session duration resolution (teamarr/consumers/racing_segments.py)
#
# `_parse_duration_from_name` and `_session_duration_hours` for endurance races
# (WEC/IMSA) whose race length varies far more than the global "racing" sport
# default allows.
# ---------------------------------------------------------------------------


class TestParseDurationFromName:
    def test_digit_hours(self):
        assert _parse_duration_from_name("24 Hours of Le Mans") == 24.0
        assert _parse_duration_from_name("6 Hours of Spa-Francorchamps") == 6.0

    def test_word_number_hours(self):
        assert _parse_duration_from_name("Mobil 1 Twelve Hours of Sebring") == 12.0

    def test_no_duration_in_name(self):
        assert _parse_duration_from_name("Rolex 24 At Daytona") is None
        assert _parse_duration_from_name("Petit Le Mans") is None
        assert _parse_duration_from_name("Battle on the Bricks") is None

    def test_none_name(self):
        assert _parse_duration_from_name(None) is None


class TestSessionDurationHours:
    def test_non_race_sessions_unaffected(self):
        assert _session_duration_hours("fp1", {}, "wec", "24 Hours of Le Mans") == 1.0
        assert _session_duration_hours("qualifying", {}, "imsa", "Petit Le Mans") == 1.0

    def test_explicit_name_duration_wins(self):
        assert _session_duration_hours("race", {}, "wec", "24 Hours of Le Mans") == 24.0
        twelve = _session_duration_hours("race", {}, "imsa", "Mobil 1 Twelve Hours of Sebring")
        assert twelve == 12.0

    def test_league_fallback_when_name_has_no_duration(self):
        assert _session_duration_hours("race", {}, "wec", "Petit Le Mans") == 6.0
        assert _session_duration_hours("race", {}, "imsa", "Battle on the Bricks") == 2.75

    def test_sport_default_for_other_leagues(self):
        assert _session_duration_hours("race", {"racing": 3.0}, "f1", "Monaco Grand Prix") == 3.0

    def test_sport_default_when_no_league(self):
        assert _session_duration_hours("race", {"racing": 3.0}) == 3.0


# ---------------------------------------------------------------------------
# Stream-name racing fallback for mixed groups (#349)
#
# The mixed-group racing fallback originally existed only on the EPG-title
# path (_match_via_epg); _match_single classified once and routed once, so a
# racing stream masked by a team_vs_team-dominant group never got a second
# chance. Both paths now share _try_racing_fallback.
# ---------------------------------------------------------------------------


def _mixed_matcher(**kw):
    from tests.fakes import make_stream_matcher

    return make_stream_matcher(
        leagues=("nfl", "mlb", "f1"),
        league_event_types={"nfl": "team_vs_team", "mlb": "team_vs_team", "f1": "event"},
        league_sports={"nfl": "football", "mlb": "baseball", "f1": "racing"},
        **kw,
    )


def _racing_outcome():
    from teamarr.consumers.matching.result import MatchMethod, MatchOutcome

    event = SimpleNamespace(league="f1", id="monaco_gp", start_time=None, short_name="Monaco GP")
    return MatchOutcome.matched(MatchMethod.FUZZY, event=event, confidence=0.9)


def _failed_route(monkeypatch, m):
    from teamarr.consumers.matching.result import MatchOutcome

    monkeypatch.setattr(
        m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)],
    )


def test_stream_name_racing_fallback_in_mixed_group(monkeypatch):
    # "F1 | Monaco Grand Prix" classifies TEAM_ONLY in a team-dominant group;
    # when the primary route fails, the fallback re-classifies as racing and
    # the result carries the RACING_EVENT classification.
    m = _mixed_matcher()
    _failed_route(monkeypatch, m)
    monkeypatch.setattr(m, "_match_racing_event", lambda classified, sid, td: _racing_outcome())
    captured = {}

    def capture(outcome, *, stream_id, stream_name, classified):
        captured["classified"] = classified
        return outcome

    monkeypatch.setattr(m, "_outcome_to_result", capture)

    out = m._match_single(1, "F1 | Monaco Grand Prix", date(2026, 6, 1))
    assert len(out) == 1
    assert out[0].is_matched
    assert captured["classified"].category == StreamCategory.RACING_EVENT


def test_stream_name_racing_fallback_requires_text_evidence(monkeypatch):
    # No racing series name in the stream → the fallback must not even attempt
    # a racing match (racing is the classifier's default bucket under "event",
    # so without this guard any unmatched stream could bind to a race).
    m = _mixed_matcher()
    _failed_route(monkeypatch, m)
    racing_called = []
    monkeypatch.setattr(
        m, "_match_racing_event",
        lambda *a, **kw: racing_called.append(1) or _racing_outcome(),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_single(1, "Random Documentary | Brimstone", date(2026, 6, 1))
    assert not racing_called
    assert not out[0].is_matched


def test_stream_name_racing_fallback_gated_by_name_match(monkeypatch):
    # Racing-by-name is a Stream Name matching type: with name_match off (and
    # Team matching on, so TEAM_ONLY still routes), the fallback must not run.
    m = _mixed_matcher()
    m._name_match_enabled = False
    _failed_route(monkeypatch, m)
    racing_called = []
    monkeypatch.setattr(
        m, "_match_racing_event",
        lambda *a, **kw: racing_called.append(1) or _racing_outcome(),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_single(1, "F1 | Monaco Grand Prix", date(2026, 6, 1))
    assert not racing_called
    assert not out[0].is_matched


def test_stream_name_racing_fallback_on_placeholder_gate(monkeypatch):
    # A timestamped racing stream with no separator ("US (Peacock 031) | IMSA
    # CTMP Grand Prix (2026-07-12 14:00:00)") classifies PLACEHOLDER in a
    # team-dominant group: the date/time extraction disqualifies TEAM_ONLY
    # and nothing else fits. It must reach the racing fallback instead of
    # being dropped as "unclassifiable".
    m = _mixed_matcher()
    monkeypatch.setattr(m, "_match_racing_event", lambda classified, sid, td: _racing_outcome())
    captured = {}

    def capture(outcome, *, stream_id, stream_name, classified):
        captured["classified"] = classified
        return outcome

    monkeypatch.setattr(m, "_outcome_to_result", capture)

    out = m._match_single(
        1, "US (Peacock 031) | IMSA CTMP Grand Prix (2026-07-12 14:00:00)", date(2026, 7, 12)
    )
    assert len(out) == 1
    assert out[0].is_matched
    assert captured["classified"].category == StreamCategory.RACING_EVENT


def test_placeholder_without_racing_evidence_stays_unclassifiable(monkeypatch):
    # A timestamped stream with NO racing series name still short-circuits as
    # unclassifiable — the fallback must not turn every dated filler stream
    # into a racing-match attempt.
    m = _mixed_matcher()
    racing_called = []
    monkeypatch.setattr(
        m, "_match_racing_event",
        lambda *a, **kw: racing_called.append(1) or _racing_outcome(),
    )

    out = m._match_single(
        1, "US (Peacock 054) | Premier League Darts (2026-07-12 19:00:00)", date(2026, 7, 12)
    )
    assert not racing_called
    assert not out[0].matched
    assert out[0].exclusion_reason == "unclassifiable"


def test_stream_name_racing_fallback_on_team_only_gate(monkeypatch):
    # Team matching OFF: a TEAM_ONLY-classified racing stream ("F1 | Monaco
    # Grand Prix") must reach the fallback instead of being dropped with
    # team_streams_disabled (mirrors the EPG path's TEAM_ONLY bypass).
    m = _mixed_matcher(team_streams_enabled=False)
    monkeypatch.setattr(m, "_match_racing_event", lambda classified, sid, td: _racing_outcome())
    captured = {}

    def capture(outcome, *, stream_id, stream_name, classified):
        captured["classified"] = classified
        return outcome

    monkeypatch.setattr(m, "_outcome_to_result", capture)

    out = m._match_single(1, "F1 | Monaco Grand Prix", date(2026, 6, 1))
    assert len(out) == 1
    assert out[0].is_matched
    assert captured["classified"].category == StreamCategory.RACING_EVENT


# ---------------------------------------------------------------------------
# Series scoping: a stream naming a specific series must only match that
# series' league(s) — and match nothing when that series isn't configured.
# ---------------------------------------------------------------------------


class TestDetectRacingSeriesLeagues:
    def test_motogp(self):
        assert detect_racing_series_leagues(
            "CA (SN+ 017) | MotoGP _ Grand Prix of Germany (2026-07-12 07:15:00)"
        ) == ("motogp",)

    def test_nascar_umbrella(self):
        assert detect_racing_series_leagues("NASCAR Cup Series at San Diego") == (
            "nascar-cup", "nascar-xfinity", "nascar-truck",
        )

    def test_wec(self):
        assert detect_racing_series_leagues("FIA WEC | ROUND 5") == ("wec",)
        assert detect_racing_series_leagues("World Endurance Championship") == ("wec",)

    def test_generic_grand_prix_is_unscoped(self):
        # "grand prix" is racing evidence but names no series — must stay
        # unscoped so a bare "Monaco Grand Prix" stream can still match F1.
        assert detect_racing_series_leagues("Monaco Grand Prix") is None

    def test_empty(self):
        assert detect_racing_series_leagues("") is None
        assert detect_racing_series_leagues("ESPN 2 (US)") is None


def test_racing_series_scoping_blocks_unconfigured_series(monkeypatch):
    # Live false-match regression: two "MotoGP - Grand Prix of Germany"
    # streams direct-matched IMSA's "Chevrolet Grand Prix" — the only racing
    # event covering the date — because motogp isn't a configured league and
    # the shared "Grand Prix" tokens cleared the single-event sanity bar. A
    # stream naming an unconfigured series must match nothing.
    m = _mixed_matcher()  # racing league available: f1 only
    _failed_route(monkeypatch, m)
    racing_called = []
    monkeypatch.setattr(
        m._racing_matcher, "match",
        lambda **kw: racing_called.append(kw["league"]) or _racing_outcome(),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_single(
        1, "CA (SN+ 017) | MotoGP _ Grand Prix of Germany (2026-07-12 07:15:00)",
        date(2026, 7, 12),
    )
    assert not racing_called  # f1 must never be attempted
    assert not out[0].matched


def test_racing_series_scoping_restricts_to_named_league(monkeypatch):
    # A stream naming IMSA in a group with several racing leagues must only
    # try imsa — not fan out across f1 too. (Racing dominates this group, so
    # the stream classifies RACING_EVENT on the primary pass and reaches
    # _match_racing_event through the real route.)
    from tests.fakes import make_stream_matcher

    m = make_stream_matcher(
        leagues=("nfl", "f1", "imsa"),
        league_event_types={"nfl": "team_vs_team", "f1": "event", "imsa": "event"},
        league_sports={"nfl": "football", "f1": "racing", "imsa": "racing"},
    )
    racing_called = []
    monkeypatch.setattr(
        m._racing_matcher, "match",
        lambda **kw: racing_called.append(kw["league"]) or _racing_outcome(),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_single(
        1, "US (Peacock 031) | IMSA CTMP Grand Prix (2026-07-12 14:00:00)", date(2026, 7, 12)
    )
    assert racing_called == ["imsa"]
    assert out[0].is_matched


def test_racing_generic_name_stays_unscoped(monkeypatch):
    # No series named ("Monaco Grand Prix") → all racing leagues remain
    # eligible, preserving pre-scoping behavior.
    m = _mixed_matcher()
    _failed_route(monkeypatch, m)
    racing_called = []
    monkeypatch.setattr(
        m._racing_matcher, "match",
        lambda **kw: racing_called.append(kw["league"]) or _racing_outcome(),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_single(1, "Monaco Grand Prix (2026-06-01 13:00:00)", date(2026, 6, 1))
    assert racing_called == ["f1"]
    assert out[0].is_matched


# ---------------------------------------------------------------------------
# Racing text evidence: WEC
# ---------------------------------------------------------------------------


def test_wec_stream_names_carry_racing_text_evidence():
    # WEC had no signature in RACING_TEXT_EVIDENCE at all, so genuine WEC
    # streams could never pass the mixed-group racing fallback gate in
    # matcher.py — WEC simply never matched.
    assert has_racing_text_evidence("WEC | Qualifying: 6 Hours of Sao Paulo")
    assert has_racing_text_evidence("FIA World Endurance Championship - Race")
    assert has_racing_text_evidence("FIA WEC Sao Paulo")
    assert not has_racing_text_evidence("Random Movie Channel")


# ---------------------------------------------------------------------------
# Session scoping: a stream whose NAME names a specific session must only
# produce that session's channel entry, not fan out across the weekend (and
# conversely, a generic stream name must not be narrowed away from sessions
# it should still cover).
# ---------------------------------------------------------------------------


def _wec_sessions():
    base = datetime(2026, 7, 11, 9, tzinfo=UTC)
    return [
        SimpleNamespace(code="fp1", name="Free Practice 1", start_time=base),
        SimpleNamespace(code="fp2", name="Free Practice 2", start_time=base + timedelta(hours=4)),
        SimpleNamespace(code="fp3", name="Free Practice 3", start_time=base + timedelta(hours=8)),
        SimpleNamespace(
            code="qualifying_lmgt3", name="Qualifying - LMGT3",
            start_time=base + timedelta(hours=12),
        ),
        SimpleNamespace(
            code="hyperpole_lmgt3", name="Hyperpole - LMGT3",
            start_time=base + timedelta(hours=12, minutes=30),
        ),
        SimpleNamespace(
            code="qualifying_hypercar", name="Qualifying - Hypercar",
            start_time=base + timedelta(hours=13),
        ),
        SimpleNamespace(
            code="hyperpole_hypercar", name="Hyperpole - Hypercar",
            start_time=base + timedelta(hours=13, minutes=30),
        ),
        SimpleNamespace(code="race", name="Race", start_time=base + timedelta(days=1)),
    ]


def _wec_event(sessions=None):
    sessions = sessions if sessions is not None else _wec_sessions()
    return SimpleNamespace(
        sport="racing",
        league="wec",
        name="6 Hours of São Paulo",
        sessions=sessions,
    )


def test_isolate_stream_session_label():
    label = _isolate_stream_session_label(
        "AU (STAN 36) | Free Practice 3: 6 Hours of Sao Paulo WEC 2026 (2026-07-11 23:00:44)"
    )
    assert label == "Free Practice 3"


def test_isolate_stream_session_label_no_delimiters():
    assert _isolate_stream_session_label("HBO UK 065") == "HBO UK 065"


class TestSessionCategoryFromStreamName:
    def test_numbered_free_practice(self):
        assert _session_category_from_stream_name(
            "AU (STAN 36) | Free Practice 3: 6 Hours of Sao Paulo WEC 2026 (2026-07-11 23:00:44)"
        ) == "fp3"

    def test_bare_qualifying(self):
        assert _session_category_from_stream_name(
            "AU (STAN 39) | Qualifying: 6 Hours of Sao Paulo WEC 2026 (2026-07-12 03:20:29)"
        ) == "qualifying"

    def test_bare_race(self):
        name = "AU (STAN) | Race: 6 Hours of Sao Paulo"
        assert _session_category_from_stream_name(name) == "race"

    def test_generic_channel_name_has_no_hint(self):
        # Linear/whole-weekend channel names must not trip narrowing.
        name = "HBO UK 065|  6 HOURS OF SAO PAULO - FIA WEC | Round 5 | 6 Hours of Sao Paulo (2026-07-11 13:00:00)"  # noqa: E501
        assert _session_category_from_stream_name(name) is None

    def test_race_as_substring_of_unrelated_branding_has_no_hint(self):
        # "race" must only count as a label when it (near enough) stands
        # alone — not as a substring of generic branding text.
        assert _session_category_from_stream_name("Sky | Race Week Live: WEC coverage") is None

    def test_plain_channel_name_has_no_hint(self):
        assert _session_category_from_stream_name("ESPN 2 (US)") is None

    def test_trailing_qualifying_keyword(self):
        # NASCAR/TSN+ convention: session type as a trailing word in the
        # label, not the whole label (unlike tsdb/STAN's bare "Qualifying").
        assert _session_category_from_stream_name(
            "CA (TSN+ 021) | NASCAR Cup Series Qualifying: Quaker State 400 (2026-07-11 16:30:00)"
        ) == "qualifying"
        assert _session_category_from_stream_name(
            "CA (TSN+ 015) | 2026 NASCAR ORAP Series Qualifying: Focused Health 250 (2026-07-11 11:00:00)"  # noqa: E501
        ) == "qualifying"

    def test_trailing_unnumbered_practice_keyword(self):
        # NASCAR emits an unnumbered "practice" session code and TSN+ labels
        # the feed "<Series> Practice" (no digit) — this must scope to the
        # practice category, not fall into the generic fan-out where the
        # practice exclusion would drop it (the exact inversion: a dedicated
        # practice feed landing on Qualifying/Race but not Practice).
        assert _session_category_from_stream_name(
            "CA (TSN+ 021) | NASCAR Cup Series Practice: Quaker State 400 (2026-07-11 14:30:00)"
        ) == "practice"

    def test_trailing_practice_requires_word_boundary(self):
        # "...practice" as a word-suffix must not match ("Malpractice").
        assert _session_category_from_stream_name(
            "US | Malpractice: Medical Drama Marathon (2026-07-11 20:00:00)"
        ) is None

    def test_no_trailing_keyword_has_no_hint(self):
        # A label ending in descriptive text (not a session word) must not
        # trip the trailing fallback.
        assert _session_category_from_stream_name(
            "2026 NASCAR CRAFTSMAN Truck Series: LiUNA 150 (2026-07-11 13:00:00)"
        ) is None
        assert _session_category_from_stream_name(
            "CA (TSN+ 036) | NASCAR Cup Series On_Board Camera: Quaker State 400 (2026-07-12 19:00:00)"  # noqa: E501
        ) is None


class TestSessionInCategory:
    def test_numbered_fp_matches_exactly(self):
        assert _session_in_category("fp3", "fp3")
        assert not _session_in_category("fp1", "fp3")

    def test_qualifying_category_covers_class_suffixed_sessions(self):
        assert _session_in_category("qualifying_lmgt3", "qualifying")
        assert _session_in_category("qualifying_hypercar", "qualifying")
        assert not _session_in_category("fp1", "qualifying")

    def test_qualifying_category_also_covers_hyperpole(self):
        # WEC's Hyperpole is itself a qualifying shootout, and providers
        # rarely label it distinctly — a bare "Qualifying" stream is a real
        # candidate for a Hyperpole session too.
        assert _session_in_category("hyperpole_lmgt3", "qualifying")
        assert _session_in_category("hyperpole_hypercar", "qualifying")
        assert _session_in_category("hyperpole", "qualifying")
        # But a stream explicitly labeled "Hyperpole" stays scoped to
        # hyperpole sessions only — narrowing is not symmetric.
        assert not _session_in_category("qualifying_lmgt3", "hyperpole")


class TestIsPracticeSession:
    def test_numbered_fp_codes(self):
        assert _is_practice_session("fp1")
        assert _is_practice_session("fp2")
        assert _is_practice_session("fp3")

    def test_bare_practice_code(self):
        assert _is_practice_session("practice")

    def test_non_practice_codes(self):
        assert not _is_practice_session("qualifying")
        assert not _is_practice_session("race")
        assert not _is_practice_session("hyperpole_lmgt3")
        assert not _is_practice_session("sprint")


def test_expand_racing_segments_scopes_dedicated_fp3_stream():
    matched = [{"stream": {"id": 1, "name": "AU (STAN) | Free Practice 3: 6 Hours of Sao Paulo"},
                "event": _wec_event()}]
    out = expand_racing_segments(matched)
    assert [m["segment"] for m in out] == ["fp3"]


def test_expand_racing_segments_scopes_bare_qualifying_to_both_classes_and_hyperpole():
    matched = [{"stream": {"id": 1, "name": "AU (STAN) | Qualifying: 6 Hours of Sao Paulo"},
                "event": _wec_event()}]
    out = expand_racing_segments(matched)
    assert {m["segment"] for m in out} == {
        "qualifying_lmgt3", "qualifying_hypercar", "hyperpole_lmgt3", "hyperpole_hypercar",
    }


def test_expand_racing_segments_keeps_full_fanout_for_generic_channel_name_excluding_practice():
    # A generic/linear channel name still fans out across everything EXCEPT
    # practice — providers rarely carry a dedicated practice feed, so a
    # whole-weekend stream landing on a Practice channel is more likely to
    # be dead air than a real source; better no channel than that.
    matched = [{
        "stream": {"id": 1, "name": "HBO UK 065|  6 HOURS OF SAO PAULO - FIA WEC | Round 5"},
        "event": _wec_event(),
    }]
    out = expand_racing_segments(matched)
    assert {m["segment"] for m in out} == {
        "qualifying_lmgt3", "hyperpole_lmgt3", "qualifying_hypercar", "hyperpole_hypercar",
        "race",
    }


def test_expand_racing_segments_still_scopes_dedicated_practice_stream():
    # The exception: a stream whose name specifically names a practice
    # session still gets that session's channel.
    matched = [{"stream": {"id": 1, "name": "AU (STAN) | Free Practice 2: 6 Hours of Sao Paulo"},
                "event": _wec_event()}]
    out = expand_racing_segments(matched)
    assert [m["segment"] for m in out] == ["fp2"]


def test_expand_racing_segments_scopes_unnumbered_trailing_practice_stream():
    # NASCAR-style weekend: an unnumbered "practice" session plus qualifying
    # and race. A TSN+ "<Series> Practice" feed must land on the practice
    # channel only.
    base = datetime(2026, 7, 11, 9, tzinfo=UTC)
    sessions = [
        SimpleNamespace(code="practice", name="Practice", start_time=base),
        SimpleNamespace(code="qualifying", name="Qualifying", start_time=base + timedelta(hours=3)),
        SimpleNamespace(code="race", name="Race", start_time=base + timedelta(days=1)),
    ]
    matched = [{
        "stream": {"id": 1, "name": "CA (TSN+ 021) | NASCAR Cup Series Practice: Quaker State 400"},
        "event": _wec_event(sessions),
    }]
    out = expand_racing_segments(matched)
    assert [m["segment"] for m in out] == ["practice"]


def test_expand_racing_segments_falls_back_when_no_session_of_the_category_exists():
    # Defensive: a hint that doesn't match anything in THIS event's sessions
    # must not silently produce zero segments for a real matched stream.
    sessions = [s for s in _wec_sessions() if s.code != "fp3"]
    matched = [{"stream": {"id": 1, "name": "AU (STAN) | Free Practice 3: 6 Hours of Sao Paulo"},
                "event": _wec_event(sessions)}]
    out = expand_racing_segments(matched)
    assert len(out) == len(sessions)


def test_expand_racing_segments_produces_no_channel_when_only_practice_exists():
    # A single-session (practice-only) event matched by a generic stream:
    # rather than land the stream on a Practice channel with nothing airing
    # yet, no segment — and so no channel — should be produced at all.
    sessions = [
        SimpleNamespace(code="practice", name="Practice",
                        start_time=datetime(2026, 7, 11, 9, tzinfo=UTC)),
    ]
    matched = [{"stream": {"id": 1, "name": "TSN+ 016"}, "event": _wec_event(sessions)}]
    out = expand_racing_segments(matched)
    assert out == []
