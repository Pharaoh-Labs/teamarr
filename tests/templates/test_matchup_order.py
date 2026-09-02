"""{matchup}/{matchup_short}/{matchup_abbrev} follow the sport's convention
(#692 phase 1): visitor first with "@" for US team sports, home first with
"v" for soccer/rugby/cricket/AFL, "v" for neutral-site games, and the
provider's title order (away then home) for individual sports."""

from datetime import UTC, datetime

from teamarr.core.naming import format_matchup, matchup_home_first
from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.identity import (
    extract_matchup,
    extract_matchup_abbrev,
    extract_matchup_short,
)


def _team(name, short, abbrev, sport, league):
    return Team(
        id=name, provider="espn", name=name, short_name=short,
        abbreviation=abbrev, league=league, sport=sport,
    )


def _ctx(home, away, sport, league, neutral_site=False):
    event = Event(
        id="1", provider="espn", name=f"{away.name} at {home.name}", short_name="x",
        start_time=datetime(2026, 9, 2, 19, 0, tzinfo=UTC),
        home_team=home, away_team=away, status=EventStatus(state="pre"),
        league=league, sport=sport, neutral_site=neutral_site,
    )
    gc = GameContext(event=event, is_home=True, team=home, opponent=away)
    tc = TeamChannelContext(team_id=home.id, league=league, sport=sport, team_name=home.name)
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


def test_format_matchup_by_sport():
    assert format_matchup("Bears", "Lions", "football") == "Bears @ Lions"
    assert format_matchup("Liverpool", "Ipswich Town", "soccer") == "Ipswich Town v Liverpool"
    neutral = format_matchup("Miami", "Ohio State", "football", neutral_site=True)
    assert neutral == "Miami v Ohio State"
    assert format_matchup("Sinner", "Alcaraz", "tennis") == "Sinner v Alcaraz"
    assert matchup_home_first("rugby") and matchup_home_first("cricket")
    assert not matchup_home_first("hockey") and not matchup_home_first(None)


def test_us_team_sport_is_visitor_first_with_at_symbol():
    ctx, gc = _ctx(
        _team("Detroit Lions", "Lions", "det", "football", "nfl"),
        _team("Chicago Bears", "Bears", "chi", "football", "nfl"),
        "football", "nfl",
    )
    assert extract_matchup(ctx, gc) == "Chicago Bears @ Detroit Lions"
    assert extract_matchup_short(ctx, gc) == "Bears @ Lions"
    assert extract_matchup_abbrev(ctx, gc) == "CHI @ DET"


def test_soccer_is_home_first_with_v():
    ctx, gc = _ctx(
        _team("Ipswich Town", "Ipswich", "ips", "soccer", "eng.1"),
        _team("Liverpool", "Liverpool", "liv", "soccer", "eng.1"),
        "soccer", "eng.1",
    )
    assert extract_matchup(ctx, gc) == "Ipswich Town v Liverpool"
    assert extract_matchup_short(ctx, gc) == "Ipswich v Liverpool"
    assert extract_matchup_abbrev(ctx, gc) == "IPS v LIV"


def test_neutral_site_us_game_keeps_order_but_reads_v():
    ctx, gc = _ctx(
        _team("Ohio State Buckeyes", "Ohio State", "osu", "football", "college-football"),
        _team("Miami Hurricanes", "Miami", "mia", "football", "college-football"),
        "football", "college-football", neutral_site=True,
    )
    assert extract_matchup_short(ctx, gc) == "Miami v Ohio State"


def test_individual_sport_keeps_provider_title_order():
    ctx, gc = _ctx(
        _team("Carlos Alcaraz", "Alcaraz", "alc", "tennis", "atp"),
        _team("Jannik Sinner", "Sinner", "sin", "tennis", "atp"),
        "tennis", "atp",
    )
    assert extract_matchup_short(ctx, gc) == "Sinner v Alcaraz"


def test_no_event_renders_empty():
    assert extract_matchup(None, None) == ""
