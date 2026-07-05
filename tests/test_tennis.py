"""Tests for tennis support (epic teamarrv2-mf7): ESPN per-match parsing,
TENNIS_MATCH classification, and TennisMatcher surname scoring.

Fixture shapes and stream names are taken from LIVE data captured during
Wimbledon 2026 (ESPN tennis/atp scoreboard + real Dispatcharr stream names),
where the full pipeline validated at ~90% match rate on 683 real streams.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    StreamCategory,
    classify_stream,
    is_racing,
    is_tennis,
)
from teamarr.consumers.matching.tennis_matcher import TennisMatcher
from teamarr.core.types import Event, EventStatus, Team
from teamarr.providers.espn.tennis import TennisParserMixin, _tennis_surnames
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    DetectionKeywordService.invalidate_cache()


# ---------------------------------------------------------------------------
# ESPN parser fixture — trimmed live Wimbledon payload shape
# ---------------------------------------------------------------------------


def _competitor(name: str, short: str, home_away: str, order: int, roster: bool = False):
    c = {"homeAway": home_away, "order": order, "type": "athlete"}
    if roster:
        c["roster"] = {"displayName": name}
        c["athlete"] = {}
    else:
        c["athlete"] = {"displayName": name, "shortName": short}
    return c


def _match(comp_id, date_str, players, status="pre", court="No. 1 Court", round_name="Round 4"):
    (n1, s1), (n2, s2) = players
    return {
        "id": comp_id,
        "date": date_str,
        "status": {"type": {"state": status, "detail": "Scheduled"}},
        "venue": {"fullName": "London, Great Britain", "court": court},
        "round": {"displayName": round_name},
        "broadcasts": [{"market": "national", "names": ["ESPN"]}],
        "notes": [{"text": f"{s2} bt {s1} 6-2 6-2", "type": "event"}] if status == "post" else [],
        "competitors": [
            _competitor(n1, s1, "away", 1, roster="/" in n1),
            _competitor(n2, s2, "home", 2, roster="/" in n2),
        ],
    }


WIMBLEDON = {
    "id": "188-2026",
    "name": "2026 Wimbledon",
    "shortName": "Wimbledon",
    "date": "2026-06-22T04:00Z",
    "endDate": "2026-07-13T03:59Z",
    "venue": {"displayName": "London, Great Britain"},
    "groupings": [
        {
            "grouping": {"displayName": "Men's Singles", "slug": "mens-singles"},
            "competitions": [
                _match(
                    "177486",
                    "2026-07-06T12:00Z",
                    [("Flavio Cobolli", "F. Cobolli"), ("Alex de Minaur", "A. de Minaur")],
                ),
                # Different date — must be sliced out for target 2026-07-06
                _match(
                    "179001",
                    "2026-07-05T11:00Z",
                    [("Qinwen Zheng", "Q. Zheng"), ("Cameron Norrie", "C. Norrie")],
                    court="Court 18",
                ),
            ],
        },
        {
            "grouping": {"displayName": "Women's Singles", "slug": "womens-singles"},
            "competitions": [
                _match(
                    "180100",
                    "2026-07-06T14:00Z",
                    [("Amanda Anisimova", "A. Anisimova"), ("Sofia Kenin", "S. Kenin")],
                ),
            ],
        },
        {
            "grouping": {"displayName": "Mixed Doubles", "slug": "mixed-doubles"},
            "competitions": [
                _match(
                    "177500",
                    "2026-07-06T12:05Z",
                    [
                        ("Laura Siegemund / Edouard Roger-Vasselin", "Siegemund/Roger-Vasselin"),
                        ("John Peers / Katie Swan", "Peers/Swan"),
                    ],
                ),
            ],
        },
    ],
}


class _Parser(TennisParserMixin):
    name = "espn"


def test_parser_expands_matches_and_gender_filters_atp():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    # atp keeps mens-singles + mixed-doubles; womens sliced out; 07-05 match sliced out
    assert {e.id for e in events} == {"188-2026-177486", "188-2026-177500"}


def test_parser_gender_filters_wta():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "wta", "tennis", date(2026, 7, 6))
    assert {e.id for e in events} == {"188-2026-180100"}


def test_atp_wta_grand_slam_split_is_disjoint():
    atp = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    wta = _Parser()._parse_tennis_matches(WIMBLEDON, "wta", "tennis", date(2026, 7, 6))
    assert not ({e.id for e in atp} & {e.id for e in wta})


def test_parser_match_fields():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    e = next(ev for ev in events if ev.id == "188-2026-177486")
    assert e.name == "Wimbledon: Flavio Cobolli vs Alex de Minaur"
    assert e.short_name == "F. Cobolli vs A. de Minaur"
    assert e.tournament_name == "Wimbledon"
    assert e.round_name == "Round 4"
    assert e.court == "No. 1 Court"
    assert e.draw_type == "Men's Singles"
    assert e.sport == "tennis"
    assert e.broadcasts == ["ESPN"]
    # homeAway mapping: de Minaur was marked home
    assert e.home_team.name == "Alex de Minaur"
    assert e.away_team.name == "Flavio Cobolli"
    # surnames as abbreviations (multi-word preserved)
    assert e.home_team.abbreviation == "de Minaur"
    assert e.away_team.abbreviation == "Cobolli"


def test_parser_doubles_roster():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    e = next(ev for ev in events if ev.id == "188-2026-177500")
    assert e.away_team.name == "Laura Siegemund / Edouard Roger-Vasselin"
    assert e.away_team.abbreviation == "Siegemund/Roger-Vasselin"


def test_surname_extraction():
    assert _tennis_surnames("Alex de Minaur") == "de Minaur"
    assert _tennis_surnames("Camilo Ugo Carabelli") == "Ugo Carabelli"
    assert _tennis_surnames("Qinwen Zheng") == "Zheng"
    assert _tennis_surnames("Hugo Nys / Edouard Roger-Vasselin") == "Nys/Roger-Vasselin"


# ---------------------------------------------------------------------------
# Classification — real stream names from the user's Dispatcharr
# ---------------------------------------------------------------------------


def test_tennis_match_stream_classifies_with_players():
    c = classify_stream(
        "Wimbledon: Zheng vs Norrie @ Jun 29 12:30 PM :Tennis  13 [1080p]",
        league_event_type="event",
        event_league_sport="tennis",
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert c.team1 and "zheng" in c.team1.lower()
    assert c.team2 and "norrie" in c.team2.lower()


def test_bbc_court_prefixed_match_stream_classifies():
    c = classify_stream(
        "(UK) (BBCi 011) | Wimbledon _ No.2 Court: Anisimova v Kenin",
        league_event_type="event",
        event_league_sport="tennis",
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert c.team1 and c.team2


def test_court_day_feed_classifies_tennis_without_players():
    c = classify_stream(
        "Wimbledon Day #6 No 1 Court ft Rybakina Zverev @ Jul 4 8:00 AM :Tennis  04",
        league_event_type="event",
        event_league_sport="tennis",
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert not (c.team1 and c.team2)
    assert c.event_hint


def test_tennis_group_does_not_classify_racing():
    # The event_type="event" racing trigger must be disabled for tennis groups
    c = classify_stream(
        "Wimbledon Day #6 No 1 Court ft Rybakina Zverev",
        league_event_type="event",
        event_league_sport="tennis",
    )
    assert c.category != StreamCategory.RACING_EVENT


def test_racing_group_unaffected_by_tennis_path():
    c = classify_stream(
        "F1: Monaco Grand Prix",
        league_event_type="event",
        event_league_sport="racing",
    )
    assert c.category == StreamCategory.RACING_EVENT


def test_legacy_racing_behavior_without_sport():
    # event_league_sport=None preserves pre-tennis behavior (racing owns "event")
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_sport_hint_routes_tennis_in_mixed_group():
    # No event-type gate (team-dominant group) — the literal "Tennis" token routes it
    c = classify_stream("Wimbledon: Sinner vs Kecmanovic @ Jun 29 1:30 PM :Tennis  21")
    assert c.category == StreamCategory.TENNIS_MATCH


def test_is_tennis_triggers():
    assert is_tennis(league_event_type="event", event_league_sport="tennis")
    assert not is_tennis(league_event_type="event", event_league_sport="racing")
    assert not is_tennis(league_event_type="event")
    assert is_tennis(league_hint="atp")
    assert is_tennis(sport_hint="Tennis")
    assert not is_tennis(sport_hint="Hockey")


def test_is_racing_sport_guard():
    assert is_racing(league_event_type="event")
    assert is_racing(league_event_type="event", event_league_sport="racing")
    assert not is_racing(league_event_type="event", event_league_sport="tennis")


# ---------------------------------------------------------------------------
# TennisMatcher scoring
# ---------------------------------------------------------------------------


def _player(name: str, surname: str) -> Team:
    return Team(
        id=f"player_{name.lower().replace(' ', '_')}",
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=surname,
        league="atp",
        sport="tennis",
    )


def _tennis_event(eid, p1, p2, start):
    return Event(
        id=eid,
        provider="espn",
        name=f"Wimbledon: {p1.name} vs {p2.name}",
        short_name=f"{p1.name} vs {p2.name}",
        start_time=start,
        home_team=p2,
        away_team=p1,
        status=EventStatus(state="scheduled"),
        league="atp",
        sport="tennis",
        tournament_name="Wimbledon",
    )


_TM = TennisMatcher(service=None, cache=None)


def test_side_score_surname_subset_beats_prefix_pollution():
    # Parsed side carries tournament + court pollution; surname subset = 100
    player = _player("Qinwen Zheng", "Zheng")
    assert _TM._side_score("wimbledon zheng", player) == 100
    assert _TM._side_score("uk bbci 011 wimbledon no 2 court zheng", player) == 100


def test_side_score_multiword_surname():
    player = _player("Alejandro Davidovich Fokina", "Davidovich Fokina")
    assert _TM._side_score("davidovich fokina", player) == 100


def test_side_score_doubles_with_underscores():
    player = _player(
        "Edouard Roger-Vasselin / Laura Siegemund", "Roger-Vasselin/Siegemund"
    )
    assert _TM._side_score("roger_vasselin siegemund", player) >= 75


def test_pair_score_requires_both_sides():
    zheng = _player("Qinwen Zheng", "Zheng")
    norrie = _player("Cameron Norrie", "Norrie")
    # One-sided surname hit must not clear the threshold
    assert _TM._pair_score("zheng", "someone else", zheng, norrie) < 75
    # Both sides straight orientation
    assert _TM._pair_score("wimbledon zheng", "norrie", norrie, zheng) == 100
    # Swapped orientation also matches
    assert _TM._pair_score("norrie", "zheng", norrie, zheng) == 100


def test_match_to_event_picks_correct_match(monkeypatch):
    tz = ZoneInfo("America/New_York")
    zheng_norrie = _tennis_event(
        "188-1",
        _player("Qinwen Zheng", "Zheng"),
        _player("Cameron Norrie", "Norrie"),
        datetime(2026, 6, 29, 12, 30, tzinfo=tz),
    )
    sinner_kecmanovic = _tennis_event(
        "188-2",
        _player("Jannik Sinner", "Sinner"),
        _player("Miomir Kecmanovic", "Kecmanovic"),
        datetime(2026, 6, 29, 13, 30, tzinfo=tz),
    )

    c = classify_stream(
        "Wimbledon: Zheng vs Norrie @ Jun 29 12:30 PM :Tennis  13 [1080p]",
        league_event_type="event",
        event_league_sport="tennis",
    )

    from teamarr.consumers.matching.tennis_matcher import TennisMatchContext

    ctx = TennisMatchContext(
        stream_name=c.normalized.original,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 29),
        generation=1,
        user_tz=tz,
        classified=c,
    )
    outcome = _TM._match_to_event(ctx, [sinner_kecmanovic, zheng_norrie], "atp")
    assert outcome.is_matched
    assert outcome.event.id == "188-1"


def test_widened_fallback_requires_unique_top(monkeypatch):
    tz = ZoneInfo("America/New_York")
    p1, p2 = _player("Qinwen Zheng", "Zheng"), _player("Cameron Norrie", "Norrie")
    e1 = _tennis_event("188-1", p1, p2, datetime(2026, 6, 29, 12, 30, tzinfo=tz))
    e2 = _tennis_event("188-9", p1, p2, datetime(2026, 6, 27, 12, 30, tzinfo=tz))

    c = classify_stream(
        "Wimbledon: Zheng vs Norrie",
        league_event_type="event",
        event_league_sport="tennis",
    )
    from teamarr.consumers.matching.tennis_matcher import TennisMatchContext

    ctx = TennisMatchContext(
        stream_name=c.normalized.original,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 29),
        generation=1,
        user_tz=tz,
        classified=c,
    )
    ambiguous = _TM._match_to_event(ctx, [e1, e2], "atp", require_unique=True)
    assert not ambiguous.is_matched

    unique = _TM._match_to_event(ctx, [e1], "atp", require_unique=True)
    assert unique.is_matched


def test_court_feed_fails_with_clear_reason():
    tz = ZoneInfo("America/New_York")
    c = classify_stream(
        "Wimbledon Day #6 No 1 Court ft Rybakina Zverev @ Jul 4 8:00 AM",
        league_event_type="event",
        event_league_sport="tennis",
    )

    class _NoService:
        def get_events(self, *a, **k):
            return []

    class _NoCache:
        def get(self, *a, **k):
            return None

        def touch(self, *a, **k):
            pass

    tm = TennisMatcher(service=_NoService(), cache=_NoCache())
    outcome = tm.match(
        c, "atp", date(2026, 7, 4), group_id=1, stream_id=1, generation=1, user_tz=tz
    )
    assert not outcome.is_matched
    assert "not yet supported" in (outcome.detail or "")
