"""RacingMatcher venue-country scoring (take-and-fix of PR #263).

venue.country is deliberately NOT a peer fuzzy candidate: token_set_ratio scores
a bare country subset at 100, so a country hit must never outrank a real
name/circuit match on a different event. It contributes only:
- to the single-covering-event sanity check (no ambiguity to create), and
- as a fallback when it identifies exactly ONE covering event.
"""

from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.racing_matcher import RacingMatchContext, RacingMatcher


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
    return object.__new__(RacingMatcher)


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
