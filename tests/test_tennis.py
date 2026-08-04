"""Tests for tennis support (epic teamarrv2-mf7): ESPN per-match parsing,
TENNIS_MATCH classification, and TennisMatcher surname scoring.

Fixture shapes and stream names are taken from LIVE data captured during
Wimbledon 2026 (ESPN tennis/atp scoreboard + real Dispatcharr stream names),
where the full pipeline validated at ~90% match rate on 683 real streams.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    CustomRegexConfig,
    StreamCategory,
    classify_stream,
    is_racing,
    is_tennis,
)
from teamarr.consumers.matching.tennis_matcher import TennisMatcher
from teamarr.core.types import Event, EventStatus, Team
from teamarr.providers.espn.tennis import TennisParserMixin, _tennis_surnames
from teamarr.services.detection_keywords import DetectionKeywordService
from teamarr.utilities.fuzzy_match import normalize_text


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
    assert {e.short_name for e in events} == {
        "F. Cobolli vs A. de Minaur",
        "Laura Siegemund / Edouard Roger-Vasselin vs John Peers / Katie Swan",
    }
    # Deterministic ids (#316): tournament + UTC date + player-pair digest —
    # NOT ESPN's unstable competition id
    for e in events:
        assert e.id.startswith("188-2026-20260706-")
    # Stable across re-parses (ESPN comp-id churn must not change identity)
    again = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    assert {e.id for e in events} == {e.id for e in again}


def test_parser_gender_filters_wta():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "wta", "tennis", date(2026, 7, 6))
    assert {e.short_name for e in events} == {"A. Anisimova vs S. Kenin"}


def test_atp_wta_grand_slam_split_is_disjoint():
    atp = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    wta = _Parser()._parse_tennis_matches(WIMBLEDON, "wta", "tennis", date(2026, 7, 6))
    assert not ({e.id for e in atp} & {e.id for e in wta})


def test_parser_match_fields():
    events = _Parser()._parse_tennis_matches(WIMBLEDON, "atp", "tennis", date(2026, 7, 6))
    e = next(ev for ev in events if ev.short_name == "F. Cobolli vs A. de Minaur")
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
    e = next(ev for ev in events if "Siegemund" in ev.short_name)
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
    e = next(ev for ev in events if ev.short_name == "F. Cobolli vs A. de Minaur")
    ctx = TemplateContext(game_context=GameContext(event=e), team_config=None, team_stats=None)
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
    ctx = TemplateContext(game_context=GameContext(event=hockey), team_config=None, team_stats=None)
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


def test_comma_form_player_pair_classifies():
    """'Surname, First - Surname, First' provider format (#439)."""
    c = classify_stream(
        "Tennis 06: Live & Upcoming: Stefanini, Lucrezia - Maria, Tatjana 07-10 13:20",
        league_event_type="event",
        event_league_sport="tennis",
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert c.team1 and "stefanini" in c.team1.lower()
    assert c.team2 and "maria" in c.team2.lower()
    assert c.separator_found == " - "


def test_comma_form_requires_commas_on_both_sides():
    """Hyphenated schedule labels must stay court/round feeds (#439 guard)."""
    for name in (
        "ATP 250 - Day 3, Court 2",  # comma only on the right side
        "Roland Garros - Second Round",  # no commas at all
    ):
        c = classify_stream(name, league_event_type="event", event_league_sport="tennis")
        assert c.category == StreamCategory.TENNIS_MATCH
        assert not (c.team1 and c.team2), name


def test_custom_teams_regex_reachable_on_tennis_path():
    """The tennis step claims streams before the cascade's custom-regex step,
    so it must consult the custom teams pattern itself (#439)."""
    cfg = CustomRegexConfig(
        teams_pattern=(r"Upcoming:\s*(?P<team1>[^-]+?)\s*-\s*(?P<team2>.+?)\s*\d{2}-\d{2}"),
        teams_enabled=True,
    )
    c = classify_stream(
        "Tennis 06: Live & Upcoming: Stefanini, Lucrezia - Maria, Tatjana 07-10 13:20",
        league_event_type="event",
        event_league_sport="tennis",
        custom_regex=cfg,
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert c.custom_regex_used
    assert c.team1 and "stefanini" in c.team1.lower()
    assert c.team2 and "maria" in c.team2.lower()


def test_custom_teams_regex_miss_falls_through_to_builtin():
    """A non-matching custom pattern must not block builtin extraction."""
    cfg = CustomRegexConfig(
        teams_pattern=r"NEVER (?P<team1>x) MATCHES (?P<team2>y)",
        teams_enabled=True,
    )
    c = classify_stream(
        "Wimbledon: Zheng vs Norrie",
        league_event_type="event",
        event_league_sport="tennis",
        custom_regex=cfg,
    )
    assert c.category == StreamCategory.TENNIS_MATCH
    assert not c.custom_regex_used
    assert c.team1 and "zheng" in c.team1.lower()
    assert c.team2 and "norrie" in c.team2.lower()


def test_comma_form_names_score_against_players():
    """Extracted comma-form sides keep the comma; surname scoring must not
    care ('Maria, Tatjana' still surname-subset-hits 'Maria')."""
    stefanini = _player("Lucrezia Stefanini", "Stefanini")
    maria = _player("Tatjana Maria", "Maria")
    score = _TM._pair_score(
        normalize_text("Stefanini, Lucrezia"),
        normalize_text("Maria, Tatjana"),
        maria,
        stefanini,
    )
    assert score == 100


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
    player = _player("Edouard Roger-Vasselin / Laura Siegemund", "Roger-Vasselin/Siegemund")
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
    assert _extract_courts("wimbledon day 6 court 18 court 16 no 2 court ft fernandez doubles") == {
        "18",
        "16",
        "2",
    }
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
    outcomes = tm.match_feed(c, ["atp", "wta"], date(2026, 7, 2), stream_id=1, user_tz=tz)
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


# ---------------------------------------------------------------------------
# Feed fan-out guards (#316): tournament + draw
# ---------------------------------------------------------------------------


def _tournament_event(eid, tournament, court, start, draw="Men's Singles", round_name="Semifinals"):
    e = _court_event(eid, "atp", court, start, round_name=round_name)
    e.tournament_name = tournament
    e.draw_type = draw
    return e


def test_court_feed_does_not_cross_tournaments():
    """A Wimbledon court stream must not join Court 1 at other tournaments."""
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 6, 8, 0, tzinfo=tz)
    events = [
        _tournament_event("wim1", "Wimbledon", "No. 1 Court", day),
        _tournament_event("nor1", "Nordea Open", "Court 1", day.replace(hour=9)),
        _tournament_event(
            "hof1",
            "Cerity Partners Hall of Fame Open for the Van Alen Cup",
            "Court 1",
            day.replace(hour=10),
        ),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Wimbledon Day #8 No 1 Court ft De Minaur Fritz @ Jul 6 8:00 AM :Tennis  05",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 6), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"wim1"}


def test_court_feed_without_tournament_hint_is_unfiltered():
    """No tournament named in the stream → pool passes through (old behavior)."""
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 6, 8, 0, tzinfo=tz)
    events = [
        _tournament_event("a1", "Wimbledon", "Court 2", day),
        _tournament_event("b1", "Nordea Open", "Court 2", day.replace(hour=9)),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Day #8 No 2 Court @ Jul 6 8:00 AM :Tennis  02",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 6), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"a1", "b1"}


def test_generic_tournament_tokens_do_not_create_hints():
    """'Open'/'Masters' alone must not read as naming a tournament."""
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 6, 8, 0, tzinfo=tz)
    events = [
        _tournament_event("a1", "Nordea Open", "Court 2", day),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Open Day #8 No 2 Court @ Jul 6 8:00 AM",  # "Open" is generic
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 6), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"a1"}


def test_round_feed_respects_declared_draw():
    """'Ladies' Singles Semifinals' must not fan onto the men's doubles semi."""
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 9, 7, 0, tzinfo=tz)
    events = [
        _tournament_event("ls1", "Wimbledon", "Centre Court", day, draw="Ladies' Singles"),
        _tournament_event(
            "ls2", "Wimbledon", "No. 1 Court", day.replace(hour=9), draw="Women's Singles"
        ),
        _tournament_event(
            "md1", "Wimbledon", "No. 1 Court", day.replace(hour=8), draw="Gentlemen's Doubles"
        ),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Ladies' Singles Semifinals @ Jul 9 7:00 AM :Tennis  01",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 9), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"ls1", "ls2"}


def test_court_feed_ft_suffix_does_not_scope_draw():
    """Court feeds cover the court's whole slate — 'ft Doubles Semifinals' is
    marketing, not scope; singles on the same court must stay."""
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 9, 8, 0, tzinfo=tz)
    events = [
        _tournament_event("s1", "Wimbledon", "No. 1 Court", day, draw="Gentlemen's Singles"),
        _tournament_event(
            "d1", "Wimbledon", "No. 1 Court", day.replace(hour=10), draw="Gentlemen's Doubles"
        ),
    ]
    tm = TennisMatcher(service=_PoolService(events), cache=_NoCache())
    c = classify_stream(
        "Wimbledon Day #11 No 1 Court ft Doubles Semifinals @ Jul 9 8:00 AM :Tennis  06",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 9), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"s1", "d1"}


def test_draw_hint_extraction():
    from teamarr.consumers.matching.tennis_matcher import _extract_draw_hints

    assert _extract_draw_hints("ladies singles semifinals") == ("women", "singles")
    assert _extract_draw_hints("gentlemens doubles semifinals") == ("men", "doubles")
    assert _extract_draw_hints("womens doubles") == ("women", "doubles")
    # "womens" must not read as "mens"
    assert _extract_draw_hints("womens singles")[0] == "women"
    assert _extract_draw_hints("mixed doubles final") == (None, "mixed")
    assert _extract_draw_hints("wimbledon day 8 no 1 court") == (None, None)


def test_parser_dedups_duplicate_competition_entries():
    """ESPN sometimes lists one match twice — deterministic ids collapse it."""
    import copy

    doubled = copy.deepcopy(WIMBLEDON)
    grouping = doubled["groupings"][0]
    dup = copy.deepcopy(grouping["competitions"][0])
    dup["id"] = "999999"  # different unstable comp id, same players/time
    grouping["competitions"].append(dup)

    events = _Parser()._parse_tennis_matches(doubled, "atp", "tennis", date(2026, 7, 6))
    names = [e.short_name for e in events]
    assert names.count("F. Cobolli vs A. de Minaur") == 1


# ---------------------------------------------------------------------------
# Majors-only subscription (#283 first slice)
# ---------------------------------------------------------------------------


def test_parser_carries_major_flag():
    import copy

    slam = copy.deepcopy(WIMBLEDON)
    slam["major"] = True
    events = _Parser()._parse_tennis_matches(slam, "atp", "tennis", date(2026, 7, 6))
    assert events and all(e.is_major for e in events)

    minor = copy.deepcopy(WIMBLEDON)
    minor["major"] = False
    events = _Parser()._parse_tennis_matches(minor, "atp", "tennis", date(2026, 7, 6))
    assert events and not any(e.is_major for e in events)


def test_majors_only_filters_feed_fanout():
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 6, 8, 0, tzinfo=tz)
    slam = _tournament_event("wim1", "Wimbledon", "No. 1 Court", day)
    slam.is_major = True
    minor = _tournament_event("nor1", "Nordea Open", "Court 1", day.replace(hour=9))
    minor.is_major = False

    tm = TennisMatcher(service=_PoolService([slam, minor]), cache=_NoCache(), majors_only=True)
    # Generic court feed with no tournament hint — majors filter must still
    # keep Nordea out of the pool entirely.
    c = classify_stream(
        "Day #8 No 1 Court @ Jul 6 8:00 AM :Tennis  02",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcomes = tm.match_feed(c, ["atp"], date(2026, 7, 6), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes if o.is_matched} == {"wim1"}

    # Same court key for both — filter must be the reason Nordea is out
    tm_off = TennisMatcher(service=_PoolService([slam, minor]), cache=_NoCache(), majors_only=False)
    outcomes_off = tm_off.match_feed(c, ["atp"], date(2026, 7, 6), stream_id=1, user_tz=tz)
    assert {o.event.id for o in outcomes_off if o.is_matched} == {"wim1", "nor1"}


def test_majors_only_filters_player_matching():
    tz = ZoneInfo("America/New_York")
    day = datetime(2026, 7, 6, 12, 0, tzinfo=tz)
    minor = _tennis_event(
        "nor2", _player("Casper Ruud", "Ruud"), _player("Holger Rune", "Rune"), day
    )
    minor.is_major = False

    tm = TennisMatcher(service=_PoolService([minor]), cache=_NoCache(), majors_only=True)
    c = classify_stream(
        "Nordea Open: Ruud vs Rune @ Jul 6 12:00 PM",
        league_event_type="event",
        event_league_sport="tennis",
    )
    outcome = tm.match(
        c,
        "atp",
        date(2026, 7, 6),
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=tz,
    )
    assert not outcome.is_matched


# ---------------------------------------------------------------------------
# Generic team paths must not reach tennis events (#541)
# ---------------------------------------------------------------------------


def test_generic_team_paths_exclude_tennis_leagues():
    """#541: an EPG programme like 'Good Day Chicago' classifies TEAM_ONLY and
    must not fuzzy-bind to 'Kayla Day vs Diane Parry' — tennis leagues are
    excluded from the generic TEAM_ONLY/TEAM_VS_TEAM/ALL_STAR candidate pools,
    so tennis events stay reachable only via the tennis pipeline (which
    enforces tennis_majors_only)."""
    from tests.fakes import make_stream_matcher

    m = make_stream_matcher(
        leagues=("wta", "atp", "mlb"),
        league_event_types={"wta": "event", "atp": "event", "mlb": "team_vs_team"},
        league_sports={"wta": "tennis", "atp": "tennis", "mlb": "baseball"},
    )

    seen: dict[str, list[str]] = {}

    def _capture_only(**kwargs):
        seen["team_only"] = kwargs["enabled_leagues"]
        return []

    def _capture_all_star(**kwargs):
        seen["all_star"] = kwargs["enabled_leagues"]
        return []

    def _capture_single(**kwargs):
        seen["single"] = [kwargs["league"]]
        return None

    m._team_matcher.match_team_only = _capture_only
    m._team_matcher.match_all_star = _capture_all_star
    m._team_matcher.match_single_league = _capture_single

    c = classify_stream("Good Day Chicago", league_event_type="team_vs_team")
    m._match_team_only(c, stream_id=1, target_date=date(2026, 8, 3))
    m._match_all_star(c, stream_id=1, target_date=date(2026, 8, 3))
    # wta/atp filtered out of the 3 search leagues -> single-league path
    m._match_team_vs_team(c, stream_id=1, target_date=date(2026, 8, 3))

    assert seen["team_only"] == ["mlb"]
    assert seen["all_star"] == ["mlb"]
    assert seen["single"] == ["mlb"]


def test_team_vs_team_filtered_when_group_is_tennis_only():
    """A tennis-only group must yield an explicit FILTERED outcome on the
    generic team path, never a fuzzy match into player-vs-player events."""
    from teamarr.consumers.matching.result import FilteredReason
    from tests.fakes import make_stream_matcher

    m = make_stream_matcher(
        leagues=("wta",),
        league_event_types={"wta": "event"},
        league_sports={"wta": "tennis"},
    )
    c = classify_stream("Day vs Parry", league_event_type="team_vs_team")
    out = m._match_team_vs_team(c, stream_id=1, target_date=date(2026, 8, 3))
    assert out.is_filtered
    assert out.filtered_reason == FilteredReason.LEAGUE_NOT_INCLUDED


def test_majors_only_gates_cache_hits():
    """Entries cached before majors-only was enabled must not keep
    resurrecting non-major matches until expiry (#541)."""
    from types import SimpleNamespace

    tz = ZoneInfo("America/New_York")

    cached_data = {
        "id": "wta-toronto-1",
        "provider": "espn",
        "name": "Kayla Day vs Diane Parry",
        "start_time": datetime(2026, 8, 3, 11, 0, tzinfo=tz).isoformat(),
        "home_team": {"name": "Kayla Day", "short_name": "Day"},
        "away_team": {"name": "Diane Parry", "short_name": "Parry"},
        "league": "wta",
        "sport": "tennis",
        "is_major": False,
    }

    class _EntryCache:
        def __init__(self):
            self.deleted = []

        def get(self, *a, **k):
            return SimpleNamespace(
                cached_data=dict(cached_data),
                league="wta",
                match_method="tennis",
                user_corrected=False,
            )

        def touch(self, *a, **k):
            pass

        def delete(self, *a, **k):
            self.deleted.append(a)

    c = classify_stream(
        "WTA Toronto: Day vs Parry @ Aug 3 11:00 AM",
        league_event_type="event",
        event_league_sport="tennis",
    )

    def _match(majors_only, cache):
        tm = TennisMatcher(service=_PoolService([]), cache=cache, majors_only=majors_only)
        return tm.match(
            c, "wta", date(2026, 8, 3),
            group_id=1, stream_id=1, generation=1, user_tz=tz,
        )

    # majors_only off: the cached non-major match is a valid hit
    cache_off = _EntryCache()
    assert _match(False, cache_off).is_matched
    assert not cache_off.deleted

    # majors_only on: same cache entry is rejected AND evicted
    cache_on = _EntryCache()
    assert not _match(True, cache_on).is_matched
    assert cache_on.deleted
