"""Integration tests for the EPG path in StreamMatcher (teamarrv2-183.4).

We exercise the EPG-specific orchestration methods (_match_via_epg,
_reconcile_epg) on a matcher built with no service/DB, patching the shared
routing. This isolates the EPG logic: category gating, EPG/window tagging,
fan-out, and reconciliation.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from teamarr.consumers.matching.classifier import StreamCategory
from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.consumers.matching.matcher import MatchedStreamResult
from teamarr.consumers.matching.result import MatchMethod, MatchOutcome
from teamarr.dispatcharr.types import DispatcharrProgram
from tests.fakes import make_stream_matcher

BASE = datetime(2026, 6, 1, 18, tzinfo=UTC)


def _prog(title="MLB Baseball", sub="Chicago Cubs at St. Louis Cardinals", cats=(), start=BASE):
    return DispatcharrProgram.from_api(
        {
            "id": 1,
            "tvg_id": "espn",
            "title": title,
            "sub_title": sub,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (start + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "epg_source": "ext",
            "custom_properties": {"categories": list(cats)} if cats else {},
        }
    )


def _bare_matcher(index, team_streams_enabled=True, racing_leagues=()):
    """A StreamMatcher with only the fields the EPG methods touch."""
    return make_stream_matcher(
        leagues=racing_leagues,
        league_event_types={lg: "event" for lg in racing_leagues},
        league_sports={lg: "racing" for lg in racing_leagues},
        team_streams_enabled=team_streams_enabled,
        epg_index=index,
    )


def _matched_outcome(event_id="e1", start=None):
    event = SimpleNamespace(league="mlb", id=event_id, start_time=start, short_name="x")
    return MatchOutcome.matched(MatchMethod.FUZZY, event=event, confidence=0.9)


def _route_one(classified, sid, td, anchor_dt=None):
    """Fake _route_to_outcomes: one matched event, id keyed to the program title
    so distinct programs (distinct matchups) produce distinct events (no dedup)."""
    return [_matched_outcome(event_id=classified.normalized.original)]


# ============================================================= _match_via_epg


def test_match_via_epg_tags_method_and_window(monkeypatch):
    index = EPGProgramIndex({"espn": [_prog()]})
    m = _bare_matcher(index)
    monkeypatch.setattr(m, "_route_to_outcomes", _route_one)
    # passthrough: return the (now-tagged) outcome so we can assert on it
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))
    assert len(out) == 1
    assert out[0].match_method == MatchMethod.EPG
    assert out[0].epg_program_start == BASE
    assert out[0].epg_program_end == BASE + timedelta(hours=3)


def test_match_via_epg_passes_program_start_as_anchor(monkeypatch):
    # bead t5e: each program is matched with its OWN broadcast instant as the
    # anchor (not the generation target_date), so the matcher can gate candidate
    # events to the live occurrence and exclude encores / the wrong night.
    n1 = datetime(2026, 6, 1, 23, tzinfo=UTC)
    n2 = datetime(2026, 6, 3, 23, tzinfo=UTC)
    progs = [
        _prog(sub="Chicago Cubs at St. Louis Cardinals", start=n1),
        _prog(sub="Los Angeles Lakers at Boston Celtics", start=n2),
    ]
    index = EPGProgramIndex({"espn": progs})
    m = _bare_matcher(index)
    anchors = []

    def fake_route(classified, sid, td, anchor_dt=None):
        anchors.append(anchor_dt)
        return [_matched_outcome(event_id=classified.normalized.original)]

    monkeypatch.setattr(m, "_route_to_outcomes", fake_route)
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)
    m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert anchors == [progs[0].start_dt, progs[1].start_dt]


def test_match_via_epg_dedupes_same_event_keeping_nearest(monkeypatch):
    # Two programs (a pre-game block and the live game) match the SAME event.
    # Only the one nearest the event start (the live broadcast) is kept, so the
    # window anchors to the live slot, not the lead-in (bead t5e).
    ev_start = datetime(2026, 6, 1, 18, tzinfo=UTC)
    pregame = _prog(sub="Cubs at Cardinals", start=ev_start - timedelta(hours=1))  # Δ=60m
    live = _prog(sub="Cubs at Cardinals", start=ev_start)                          # Δ=0
    index = EPGProgramIndex({"espn": [pregame, live]})
    m = _bare_matcher(index)
    monkeypatch.setattr(
        m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [_matched_outcome(event_id="game1", start=ev_start)],
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))
    assert len(out) == 1
    assert out[0].epg_program_start == live.start_dt  # nearest the event, not pre-game


def test_match_via_epg_skips_non_event_before_routing(monkeypatch):
    index = EPGProgramIndex({"espn": [_prog(cats=("Sports non-event",))]})
    m = _bare_matcher(index)
    routed = []
    monkeypatch.setattr(m, "_route_to_outcomes", lambda *a, **k: routed.append(1) or [])
    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))
    assert out == []
    assert not routed  # gated by should_attempt() before the matcher runs


def test_match_via_epg_skips_classic_replay(monkeypatch):
    index = EPGProgramIndex({"espn": [_prog(cats=("Sports event", "Classic Sport Event"))]})
    m = _bare_matcher(index)
    routed = []
    monkeypatch.setattr(m, "_route_to_outcomes", lambda *a, **k: routed.append(1) or [])
    assert m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1)) == []
    assert not routed


def test_match_via_epg_fans_out_one_per_program(monkeypatch):
    progs = [
        _prog(sub="Chicago Cubs at St. Louis Cardinals", start=BASE),
        _prog(sub="Los Angeles Lakers at Boston Celtics", start=BASE + timedelta(hours=4)),
    ]
    index = EPGProgramIndex({"espn": progs})
    m = _bare_matcher(index)
    monkeypatch.setattr(m, "_route_to_outcomes", _route_one)
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)
    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))
    # one matched result per program (distinct matchups → distinct events)
    assert len(out) == 2
    assert out[0].epg_program_start == BASE
    assert out[1].epg_program_start == BASE + timedelta(hours=4)


def test_match_via_epg_carries_each_program_slot(monkeypatch):
    # Each matched program carries its own broadcast slot (start/end) for the
    # lifecycle attach/detach window. Clipping was removed (bead 6qx), so
    # back-to-back programs are independent — no neighbour boundaries involved.
    p0 = _prog(sub="A at B", start=BASE - timedelta(hours=2))            # 16:00-19:00
    p1 = _prog(sub="Chicago Cubs at St. Louis Cardinals", start=BASE)    # 18:00-21:00
    p2 = _prog(sub="C at D", start=BASE + timedelta(hours=4))            # 22:00-01:00
    index = EPGProgramIndex({"espn": [p0, p1, p2]})
    m = _bare_matcher(index)
    monkeypatch.setattr(m, "_route_to_outcomes", _route_one)
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))
    assert [r.epg_program_start for r in out] == [p0.start_dt, p1.start_dt, p2.start_dt]
    assert [r.epg_program_end for r in out] == [p0.end_dt, p1.end_dt, p2.end_dt]
    assert not hasattr(out[1], "epg_clip_before")


def test_match_via_epg_drops_unmatched_outcomes(monkeypatch):
    index = EPGProgramIndex({"espn": [_prog()]})
    m = _bare_matcher(index)
    monkeypatch.setattr(
        m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)],  # not matched
    )
    assert m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1)) == []


# ============================================================== _reconcile_epg


def _result(matched, method=MatchMethod.FUZZY):
    return MatchedStreamResult(
        stream_name="x", stream_id=1, matched=matched, match_method=method
    )


def _epg_result():
    return MatchedStreamResult(
        stream_name="x", stream_id=1, matched=True, match_method=MatchMethod.EPG,
        epg_program_start=BASE,
    )


def test_reconcile_linear_epg_wins_over_name():
    # two programs => linear; EPG matched => EPG wins, name discarded
    index = EPGProgramIndex({"espn": [_prog(), _prog(start=BASE + timedelta(hours=4))]})
    m = _bare_matcher(index)
    name = [_result(matched=True)]
    epg = [_epg_result(), _epg_result()]
    out = m._reconcile_epg(name, epg, "espn")
    assert out == epg


def test_reconcile_linear_no_epg_keeps_name():
    index = EPGProgramIndex({"espn": [_prog(), _prog(start=BASE + timedelta(hours=4))]})
    m = _bare_matcher(index)
    name = [_result(matched=False)]
    out = m._reconcile_epg(name, [], "espn")
    assert out == name


def test_reconcile_dedicated_name_wins():
    # single program => dedicated; name match kept even if EPG also matched
    index = EPGProgramIndex({"espn": [_prog()]})
    m = _bare_matcher(index)
    name = [_result(matched=True)]
    epg = [_epg_result()]
    out = m._reconcile_epg(name, epg, "espn")
    assert out == name


def test_reconcile_dedicated_epg_fills_when_name_empty():
    index = EPGProgramIndex({"espn": [_prog()]})
    m = _bare_matcher(index)
    name = [_result(matched=False)]
    epg = [_epg_result()]
    out = m._reconcile_epg(name, epg, "espn")
    assert out == epg


# ============================================ racing fallback in _match_via_epg
#
# In a mixed group (team-sport dominant), racing EPG titles don't classify as
# RACING_EVENT on the primary pass — they land as TEAM_VS_TEAM (NASCAR "at City"
# format) or TEAM_ONLY (F1/WEC separator-free titles).  The racing fallback must
# re-classify them under league_event_type="event" and try the racing matcher.


def _racing_matched_outcome(event_id="race1", start=None):
    ev = SimpleNamespace(
        league="nascar-cup", id=event_id, start_time=start or BASE, short_name="Daytona 500"
    )
    return MatchOutcome.matched(MatchMethod.FUZZY, event=ev, confidence=0.9)


def test_epg_racing_fallback_nascar_at_city(monkeypatch):
    # NASCAR "at City" EPG format: title="NASCAR Cup Series", sub="at San Diego"
    # → build_match_input → "NASCAR Cup Series | at San Diego"
    # In a mixed group the DOMINANT type is "team_vs_team", so this classifies
    # TEAM_VS_TEAM on the primary pass.  Primary team route finds no match;
    # racing fallback re-classifies with "event" type → RACING_EVENT and matches.
    prog = _prog(title="NASCAR Cup Series", sub="at San Diego")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=True, racing_leagues=("nascar-cup",))
    # Simulate a mixed group: dominant type is "team_vs_team" (NASCAR is a minority)
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)])
    monkeypatch.setattr(m, "_match_racing_event",
        lambda classified, sid, td: _racing_matched_outcome())
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert len(out) == 1
    assert out[0].match_method == MatchMethod.EPG
    assert out[0].epg_program_start == BASE
    assert out[0].event.id == "race1"


def test_epg_racing_fallback_f1_team_only(monkeypatch):
    # F1 separator-free EPG: title="Formula 1", sub="Monaco Grand Prix"
    # → "Formula 1 | Monaco Grand Prix" → TEAM_ONLY in a mixed group.
    # With team_streams_enabled=False, the TEAM_ONLY gate normally returns early —
    # but it must not when racing leagues are present.
    prog = _prog(title="Formula 1", sub="Monaco Grand Prix")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=False, racing_leagues=("f1",))
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    routed = []
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: routed.append(1) or [])
    race_ev = SimpleNamespace(league="f1", id="monaco_gp", start_time=BASE, short_name="Monaco GP")
    monkeypatch.setattr(
        m,
        "_match_racing_event",
        lambda classified, sid, td: MatchOutcome.matched(
            MatchMethod.FUZZY, event=race_ev, confidence=0.9
        ),
    )
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert len(out) == 1
    assert out[0].match_method == MatchMethod.EPG
    assert out[0].event.id == "monaco_gp"
    assert not routed  # TEAM_ONLY gate was bypassed, not routed through team path


def test_epg_racing_fallback_not_triggered_for_team_sport_title(monkeypatch):
    # "MLB Baseball | Chicago Cubs at St. Louis Cardinals" must not produce a
    # racing match even in a mixed group with racing leagues present. The racing
    # fallback may attempt a match but the racing matcher returns no result for
    # a baseball title, so the final output is still empty.
    prog = _prog(title="MLB Baseball", sub="Chicago Cubs at St. Louis Cardinals")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=True, racing_leagues=("nascar-cup",))
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)])
    monkeypatch.setattr(m, "_match_racing_event",
        lambda *a, **kw: MatchOutcome.failed(None))
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert out == []


def test_epg_racing_fallback_not_triggered_without_racing_leagues(monkeypatch):
    # Without racing leagues in the group, _try_racing_fallback must bail out
    # immediately — even if the EPG title happens to look like a racing stream.
    prog = _prog(title="NASCAR Cup Series", sub="at San Diego")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=True, racing_leagues=())
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)])
    racing_called = []
    monkeypatch.setattr(m, "_match_racing_event",
        lambda *a, **kw: racing_called.append(1) or MatchOutcome.failed(None))
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert out == []
    assert not racing_called


def test_epg_racing_fallback_uses_racing_classification_in_result(monkeypatch):
    # The result returned from the racing fallback must carry the RACING_EVENT
    # classification (not the original TEAM_VS_TEAM), so downstream rules that
    # key on category (e.g. stream ordering) see the right type.
    prog = _prog(title="NASCAR Cup Series", sub="at San Diego")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=True, racing_leagues=("nascar-cup",))
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)])
    monkeypatch.setattr(m, "_match_racing_event",
        lambda classified, sid, td: _racing_matched_outcome())
    captured = {}
    def capture_result(outcome, *, stream_id, stream_name, classified):
        captured["category"] = classified.category
        outcome.match_method = MatchMethod.EPG
        outcome.epg_program_start = BASE
        outcome.epg_program_end = BASE + timedelta(hours=3)
        return outcome
    monkeypatch.setattr(m, "_outcome_to_result", capture_result)

    m._match_via_epg(100, "ESPN", "espn", date(2026, 6, 1))

    assert captured.get("category") == StreamCategory.RACING_EVENT


def test_epg_racing_fallback_requires_text_evidence(monkeypatch):
    # teamarrv2-w42k: with league_event_type="event", RACING_EVENT is the
    # classifier's default bucket, so without a text gate ANY unmatched
    # programme (documentary, movie) reaches the racing matcher and can bind
    # to the day's race by date coverage — one run produced 853 false
    # stream-event pairs ("Impossible Repairs" → Pirelli British GP).
    # The fallback must skip titles with no motorsports series name.
    prog = _prog(title="Impossible Repairs", sub="Big City Tunnel Boring Machine")
    index = EPGProgramIndex({"espn": [prog]})
    m = _bare_matcher(index, team_streams_enabled=True, racing_leagues=("f1",))
    monkeypatch.setattr(m, "_get_dominant_event_type", lambda: "team_vs_team")
    monkeypatch.setattr(m, "_route_to_outcomes",
        lambda c, sid, td, anchor_dt=None: [MatchOutcome.failed(None)])
    racing_called = []
    monkeypatch.setattr(m, "_match_racing_event",
        lambda classified, sid, td: racing_called.append(1) or _racing_matched_outcome())
    monkeypatch.setattr(m, "_outcome_to_result", lambda outcome, **kw: outcome)

    out = m._match_via_epg(100, "US: Smithsonian Channel", "espn", date(2026, 6, 1))

    assert racing_called == []  # racing matcher never consulted
    assert out == []
