"""Integration tests for the EPG path in StreamMatcher (teamarrv2-183.4).

StreamMatcher's constructor does DB work, so we exercise the EPG-specific
orchestration methods (_match_via_epg, _reconcile_epg) on a bare instance with
the few attributes they touch, patching the shared routing. This isolates the
EPG logic: category gating, EPG/window tagging, fan-out, and reconciliation.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.consumers.matching.matcher import MatchedStreamResult, StreamMatcher
from teamarr.consumers.matching.result import MatchMethod, MatchOutcome
from teamarr.dispatcharr.types import DispatcharrProgram

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


def _bare_matcher(index, team_streams_enabled=True):
    """A StreamMatcher with only the fields the EPG methods touch."""
    m = object.__new__(StreamMatcher)
    m._epg_index = index
    m._custom_regex = None
    m._feed_home_terms = None
    m._feed_away_terms = None
    m._team_streams_enabled = team_streams_enabled
    m._league_event_types = {}
    m._user_tz = ZoneInfo("UTC")
    return m


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
