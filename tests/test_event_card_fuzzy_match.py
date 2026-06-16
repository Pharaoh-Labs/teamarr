"""Fuzzy event-name matching (Strategy 3) for combat event cards — PR #239.

Named combat events without a standard number (e.g. "UFC at the White House")
should fuzzy-match an event by name, while generic streams (just "UFC | Main
Card") should NOT match anything. event_hint / team1 / team2 are None so
strategies 1 (event number) and 2 (fighter names) are skipped and strategy 3 is
exercised in isolation; it only reads ``event.name``, so stand-in events suffice.
"""

from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.event_matcher import EventCardMatcher, EventMatchContext
from teamarr.consumers.matching.result import MatchMethod


def _ctx(stream_name: str) -> EventMatchContext:
    return EventMatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 14),
        generation=0,
        user_tz=ZoneInfo("UTC"),
        classified=SimpleNamespace(event_hint=None, team1=None, team2=None),
    )


def test_fuzzy_matches_named_event_without_number():
    matcher = EventCardMatcher(service=None, cache=None)
    ctx = _ctx("LIVE | UFC at the White House | Main Card")
    events = [
        SimpleNamespace(name="UFC Fight Night: Smith vs Jones"),
        SimpleNamespace(name="UFC at the White House: Topuria vs Gaethje"),
    ]
    outcome = matcher._match_to_event_card(ctx, events, "ufc")
    assert outcome.is_matched
    assert outcome.match_method == MatchMethod.FUZZY
    assert outcome.event is events[1]


def test_generic_stream_does_not_fuzzy_match():
    # All tokens are noise (ufc/live/main card) -> no distinct name -> no match.
    matcher = EventCardMatcher(service=None, cache=None)
    ctx = _ctx("LIVE | UFC | Main Card")
    events = [SimpleNamespace(name="UFC 300: Pereira vs Hill")]
    outcome = matcher._match_to_event_card(ctx, events, "ufc")
    assert not outcome.is_matched
