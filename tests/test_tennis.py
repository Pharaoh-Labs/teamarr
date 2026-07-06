"""Tests for tennis support (epic teamarrv2-mf7): ESPN per-match parsing,
TENNIS_MATCH classification, and TennisMatcher surname scoring.

Fixture shapes and stream names are taken from LIVE data captured during
Wimbledon 2026 (ESPN tennis/atp scoreboard + real Dispatcharr stream names),
where the full pipeline validated at ~90% match rate on 683 real streams.
"""

from datetime import date, datetime, timedelta
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


def test_parser_title_is_away_vs_home_even_when_home_listed_first():
    # ESPN usually lists away first, but the title ordering must be
    # deterministic (away vs home) so {player1}/{player2} always match it.
    tournament = {
        "id": "188-2026",
        "shortName": "Wimbledon",
        "venue": {"displayName": "London, Great Britain"},
        "groupings": [
            {
                "grouping": {"displayName": "Men's Singles", "slug": "mens-singles"},
                "competitions": [
                    {
                        "id": "900",
                        "date": "2026-07-06T12:00Z",
                        "status": {"type": {"state": "pre"}},
                        "venue": {"fullName": "London", "court": "Court 5"},
                        "round": {"displayName": "Round 4"},
                        "competitors": [
                            _competitor("Home First", "H. First", "home", 1),
                            _competitor("Away Second", "A. Second", "away", 2),
                        ],
                    }
                ],
            }
        ],
    }
    events = _Parser()._parse_tennis_matches(tournament, "atp", "tennis", date(2026, 7, 6))
    assert len(events) == 1
    e = events[0]
    assert e.name == "Wimbledon: Away Second vs Home First"
    assert e.short_name == "A. Second vs H. First"
    assert e.home_team.name == "Home First"
    assert e.away_team.name == "Away Second"


# ---------------------------------------------------------------------------
# Template variables — {player1}/{player2} mirror combat's fighter1/fighter2
# ---------------------------------------------------------------------------


def test_player_variables_match_title_order():
    from teamarr.templates.context import GameContext, TemplateContext
    from teamarr.templates.variables.tennis import (
        extract_player1,
        extract_player1_last,
        extract_player2,
        extract_player2_last,
        extract_tournament_name,
    )

    events = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    e = next(ev for ev in events if ev.id == "188-2026-177486")
    ctx = TemplateContext(
        game_context=GameContext(event=e), team_config=None, team_stats=None
    )
    game_ctx = ctx.game_context

    # Title is "Wimbledon: Flavio Cobolli vs Alex de Minaur" — player1 = Cobolli
    assert extract_player1(ctx, game_ctx) == "Flavio Cobolli"
    assert extract_player2(ctx, game_ctx) == "Alex de Minaur"
    assert extract_player1_last(ctx, game_ctx) == "Cobolli"
    assert extract_player2_last(ctx, game_ctx) == "de Minaur"
    assert extract_tournament_name(ctx, game_ctx) == "Wimbledon"


def test_player_variables_empty_for_non_tennis():
    from teamarr.templates.context import GameContext, TemplateContext
    from teamarr.templates.variables.tennis import extract_player1

    hockey = _tennis_event(
        "x", _player("A B", "B"), _player("C D", "D"), datetime(2026, 7, 6, tzinfo=ZoneInfo("UTC"))
    )
    hockey.sport = "hockey"
    ctx = TemplateContext(
        game_context=GameContext(event=hockey), team_config=None, team_stats=None
    )
    assert extract_player1(ctx, ctx.game_context) == ""


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


# ---------------------------------------------------------------------------
# EPG path: tennis programme titles are gated out pending mf7.9
# ---------------------------------------------------------------------------


def test_epg_path_skips_tennis_programmes():
    """Tennis EPG matching needs its own design (mf7.9) — one guide programme
    covers many concurrent matches. Until then, tennis-classified programme
    titles must be dropped from the EPG path, not routed to the matcher
    (2026-07-05 regression: match volume 166→1,099 on the channel-source
    group when programme titles reached the tennis pipeline)."""
    from zoneinfo import ZoneInfo as _Z

    from teamarr.consumers.matching.epg_index import EPGProgramIndex
    from teamarr.dispatcharr.types import DispatcharrProgram
    from tests.fakes import make_stream_matcher

    start = datetime(2026, 7, 5, 13, tzinfo=_Z("UTC"))
    prog = DispatcharrProgram.from_api(
        {
            "id": 1,
            "tvg_id": "espn",
            "title": "Tennis: Wimbledon",
            "sub_title": "Sabalenka vs Osaka",
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": "2026-07-05T16:00:00Z",
            "epg_source": "ext",
            "custom_properties": {},
        }
    )
    m = make_stream_matcher(
        leagues=("atp", "wta"),
        league_event_types={"atp": "event", "wta": "event"},
        league_sports={"atp": "tennis", "wta": "tennis"},
        epg_index=EPGProgramIndex({"espn": [prog]}),
        user_tz=_Z("UTC"),
    )

    called = []
    m._route_to_outcomes = lambda *a, **k: called.append(1) or []

    results = m._match_via_epg(
        stream_id=1, stream_name="ESPN", tvg_id="espn", target_date=date(2026, 7, 5)
    )
    assert results == []
    assert not called  # programme never reached the matcher


# ---------------------------------------------------------------------------
# Court/round feed matching (phase 2, mf7.7)
# ---------------------------------------------------------------------------

from teamarr.consumers.matching.tennis_matcher import (  # noqa: E402
    _court_key,
    _extract_courts,
    _extract_round,
)


def test_court_extraction_from_real_stream_names():
    # Real Dispatcharr stream names (normalized: lowercase, dots stripped)
    assert _extract_courts("wimbledon day 6 no 1 court ft rybakina zverev") == {"1"}
    assert _extract_courts("wimbledon day 4 court 4 and court 12 ft fernandez doubles") == {
        "4",
        "12",
    }
    assert _extract_courts("wimbledon day 5 centre court ft djokovic sabalenka") == {"centre"}
    assert _extract_courts(
        "wimbledon day 6 court 18 court 16 no 2 court ft fernandez doubles"
    ) == {"18", "16", "2"}
    assert _extract_courts("wimbledon second round") == set()


def test_court_key_canonicalizes_espn_values():
    assert _court_key("No. 1 Court") == "1"
    assert _court_key("Centre Court") == "centre"
    assert _court_key("Court 18") == "18"
    assert _court_key("Court 17 Roehampton") == "17"
    assert _court_key("Show Court 1 Roehampton") == "show 1"


def test_round_extraction():
    assert _extract_round("wimbledon second round") == "round 2"
    assert _extract_round("wimbledon round 3") == "round 3"
    assert _extract_round("wimbledon quarterfinals day 9") == "quarterfinals"
    assert _extract_round("wimbledon semi final") == "semifinals"
    assert _extract_round("wimbledon final") == "final"
    assert _extract_round("wimbledon day 6 no 1 court") is None
    # Spanish/French round-of-N phrases name EARLIER rounds — not the final
    assert _extract_round("wimbledon octavos de final") is None
    assert _extract_round("cuartos de final wimbledon") is None


class _PoolService:
    def __init__(self, events):
        self._events = events

    def get_events(self, league, target_date, cache_only=False):
        return [e for e in self._events if e.league == league]


class _NoCache:
    def get(self, *a, **k):
        return None

    def touch(self, *a, **k):
        pass


def _court_event(eid, league, court, start, round_name="Round 4"):
    e = _tennis_event(
        eid,
        _player(f"Player {eid}A", f"{eid}A"),
        _player(f"Player {eid}B", f"{eid}B"),
        start,
    )
    e.court = court
    e.round_name = round_name
    e.league = league
    return e


def test_court_feed_fans_out_to_courts_matches():
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 4, 8, 0, tzinfo=tz)
    events = [
        _court_event("m1", "atp", "No. 1 Court", day),
        _court_event("m2", "wta", "No. 1 Court", day.replace(hour=10)),
        _court_event("m3", "atp", "Court 18", day),  # different court
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())

    c = classify_stream(
        "Wimbledon Day #6 No 1 Court ft Rybakina Zverev @ Jul 4 8:00 AM :Tennis  04",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(
        c, ["atp", "wta"], date(2026, 7, 4), stream_id=1, user_tz=tz, duration_hours=3.0
    )
    matched_ids = {o.event.id for o in outcomes if o.is_matched}
    assert matched_ids == {"m1", "m2"}  # both tours' matches on No.1 Court
    # each outcome carries its own time-share window
    for o in outcomes:
        assert o.epg_program_start == o.event.start_time
        assert o.epg_program_end == o.event.start_time + timedelta(hours=3)


def test_round_feed_fans_out_to_rounds_matches():
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 2, 6, 0, tzinfo=tz)
    events = [
        _court_event("r1", "atp", "Court 5", day, round_name="Round 2"),
        _court_event("r2", "wta", "Court 8", day, round_name="Round 2"),
        _court_event("r3", "atp", "Court 5", day.replace(hour=12), round_name="Round 1"),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())

    c = classify_stream(
        "Wimbledon Second Round @ Jul 2 5:00 AM :Tennis  01",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(
        c, ["atp", "wta"], date(2026, 7, 2), stream_id=1, user_tz=tz
    )
    assert {o.event.id for o in outcomes if o.is_matched} == {"r1", "r2"}


def test_ambient_feed_fails_with_clear_reason():
    tz = ZoneInfo("America/New_York")
    tm = TennisMatcher(service=_PoolService([]), cache=_NoCache())
    c = classify_stream(
        "Wimbledon Press Conferences",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 4), stream_id=1, user_tz=tz)
    assert len(outcomes) == 1 and not outcomes[0].is_matched
    assert "Ambient tennis feed" in (outcomes[0].detail or "")


def test_court_feed_no_matches_on_court_fails():
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 4, 8, 0, tzinfo=tz)
    events = [_court_event("m3", "atp", "Court 18", day)]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Wimbledon Day #6 No 1 Court @ Jul 4 8:00 AM",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 4), stream_id=1, user_tz=tz)
    assert len(outcomes) == 1 and not outcomes[0].is_matched
    assert "No tennis matches on" in (outcomes[0].detail or "")
