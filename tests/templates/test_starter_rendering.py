"""Starter-set rendering against Gracenote conventions (tvnk.9, #329).

Renders every starter template's text surfaces through the REAL resolver
(variable extraction, condition selection, cleanup/capitalization) with
family-appropriate contexts, and asserts CONVENTION parity — grammar,
articles, separators, field register — never verbatim Gracenote text
(maintainer acceptance framing on epic tvnk: Gracenote editorial isn't
licensable and isn't the goal).

Conventions under test (docs/reference/gracenote-categories.md):
- club/franchise teams take "the", national teams and soccer clubs don't
- college register is home-led host framing with rank + record
- soccer register is "X face Y", channel connector 'v'
- tournament titles are year-composed ("FIFA World Cup 2026")
- MiLB titles as "Minor League Baseball" (via the seeded category)
"""

from datetime import UTC, datetime

import pytest

from teamarr.core.types import Event, EventStatus, Team, TeamStats, Venue
from teamarr.database.default_templates import DEFAULT_TEMPLATE_SET
from teamarr.services import league_mappings as lm
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver

SPECS = {spec["name"]: spec for spec in DEFAULT_TEMPLATE_SET}


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    """The real LeagueMappingService over the seeded temp DB — gracenote
    categories, aliases, and event_types resolve exactly as in production."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture
def resolver():
    return TemplateResolver()


def _team(name, abbrev, league, sport, id_="1", short=None):
    return Team(
        id=id_, provider="espn", name=name, short_name=short or name,
        abbreviation=abbrev, league=league, sport=sport,
    )


_VENUE = Venue(name="The Palace", city="Auburn Hills", state="MI")


def _event(home, away, league, sport, *, state="pre", venue=_VENUE, **kw):
    return Event(
        id="e1", provider="espn", name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=datetime(2026, 7, 10, 19, 0, tzinfo=UTC),
        home_team=home, away_team=away, status=EventStatus(state=state),
        league=league, sport=sport, venue=venue, **kw,
    )


def _ctx(event, *, team=None, team_stats=None, opponent_stats=None, **kw):
    """Context for the given event; the channel 'team' defaults to home."""
    team = team or event.home_team
    game_ctx = GameContext(
        event=event,
        is_home=(team.id == event.home_team.id),
        opponent_stats=opponent_stats,
        **kw,
    )
    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=team.id, league=event.league, sport=event.sport,
            team_name=team.name, team_abbrev=team.abbreviation,
        ),
        team_stats=team_stats,
        next_game=game_ctx,
        last_game=game_ctx,
    )


# --- family contexts -------------------------------------------------------


def _nba_ctx(**kw):
    home = _team("Boston Celtics", "BOS", "nba", "basketball", "1")
    away = _team("Detroit Pistons", "DET", "nba", "basketball", "2")
    ev = _event(home, away, "nba", "basketball",
                home_last_five="4-1", away_last_five="2-3",
                series_summary="Series tied 1-1", **kw)
    return _ctx(ev, team_stats=TeamStats(record="10-2"),
                opponent_stats=TeamStats(record="8-4"))


def _soccer_club_ctx(**kw):
    home = _team("Chelsea", "CHE", "eng.1", "soccer", "1")
    away = _team("Arsenal", "ARS", "eng.1", "soccer", "2")
    ev = _event(home, away, "eng.1", "soccer",
                venue=Venue(name="Stamford Bridge", city="London"),
                home_last_five="3-2", away_last_five="4-1", **kw)
    return _ctx(ev, team_stats=TeamStats(record="10-2-5"),
                opponent_stats=TeamStats(record="12-3-2"))


def _national_ctx(**kw):
    home = _team("Spain", "ESP", "fifa.world", "soccer", "1")
    away = _team("Belgium", "BEL", "fifa.world", "soccer", "2")
    ev = _event(home, away, "fifa.world", "soccer",
                venue=Venue(name="MetLife Stadium", city="East Rutherford"),
                home_last_five="4-1", away_last_five="3-2", **kw)
    return _ctx(ev)


def _college_ctx(*, home_rank=None, away_rank=None, conference=None, **kw):
    home = _team("Arkansas Razorbacks", "ARK", "mens-college-basketball", "basketball", "1")
    away = _team("Texas A&M Aggies", "TAMU", "mens-college-basketball", "basketball", "2")
    ev = _event(home, away, "mens-college-basketball", "basketball",
                venue=Venue(name="Bud Walton Arena", city="Fayetteville", state="AR"),
                home_last_five="4-1", away_last_five="3-2", **kw)
    return _ctx(
        ev,
        team_stats=TeamStats(record="20-7", rank=home_rank, conference=conference),
        opponent_stats=TeamStats(record="19-8", rank=away_rank, conference=conference),
    )


def _combat_ctx(**kw):
    f1 = _team("Alexander Volkanovski", "VOL", "ufc", "mma", "1")
    f2 = _team("Diego Lopes", "LOP", "ufc", "mma", "2")
    ev = Event(
        id="e1", provider="espn", name="UFC 325: Volkanovski vs Lopes",
        short_name="UFC 325", start_time=datetime(2026, 7, 10, 22, 0, tzinfo=UTC),
        home_team=f1, away_team=f2, status=EventStatus(state="pre"),
        league="ufc", sport="mma", venue=Venue(name="T-Mobile Arena", city="Las Vegas"),
    )
    game_ctx = GameContext(event=ev, is_home=True, card_segment="main_card", **kw)
    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id="1", league="ufc", sport="mma", team_name=f1.name,
        ),
        team_stats=None, next_game=game_ctx, last_game=game_ctx,
    )


def _tennis_ctx(**kw):
    p1 = _team("Carlos Alcaraz", "ALC", "atp", "tennis", "1")
    p2 = _team("Jannik Sinner", "SIN", "atp", "tennis", "2")
    ev = _event(p1, p2, "atp", "tennis",
                venue=Venue(name="Centre Court", city="London"),
                tournament_name="Wimbledon", round_name="Final",
                draw_type="Men's Singles", is_major=True, **kw)
    return _ctx(ev)


def _milb_ctx(**kw):
    home = _team("Sugar Land Space Cowboys", "SUG", "milb-aaa", "baseball", "1")
    away = _team("Albuquerque Isotopes", "ABQ", "milb-aaa", "baseball", "2")
    ev = _event(home, away, "milb-aaa", "baseball", **kw)
    return _ctx(ev, team_stats=TeamStats(record="40-30"),
                opponent_stats=TeamStats(record="35-35"))


_CTX_FOR_TEMPLATE = {
    "Default Team (Starter)": _nba_ctx,
    "Soccer Team (Starter)": _soccer_club_ctx,
    "College Team (Starter)": lambda: _college_ctx(home_rank=20, away_rank=15),
    "Default Event (Starter)": _nba_ctx,
    "College Event (Starter)": lambda: _college_ctx(home_rank=20, away_rank=15),
    "Soccer Club Event (Starter)": _soccer_club_ctx,
    "Combat Event (Starter)": _combat_ctx,
    "International Event (Starter)": _national_ctx,
    "Tennis Event (Starter)": _tennis_ctx,
}


def _text_surfaces(spec):
    """Every user-visible text template in a starter spec, labeled."""
    for key in ("title_format", "subtitle_template", "event_channel_name"):
        if spec.get(key):
            yield key, spec[key]
    for i, row in enumerate(spec.get("conditional_descriptions") or []):
        yield f"conditional[{i}] ({row.get('label')})", row["template"]
    for section in ("pregame_fallback", "postgame_fallback", "idle_content"):
        for key, val in (spec.get(section) or {}).items():
            if key != "art_url" and isinstance(val, str) and val:
                yield f"{section}.{key}", val
    for section in ("postgame_conditional", "idle_conditional"):
        block = spec.get(section) or {}
        if block.get("enabled"):
            for key in ("description_final", "description_not_final"):
                if block.get(key):
                    yield f"{section}.{key}", block[key]


# --- every surface of every starter renders clean --------------------------


@pytest.mark.parametrize("name", sorted(SPECS))
def test_starter_renders_every_surface_clean(name, resolver):
    """No unresolved tokens, no double spaces, no orphan punctuation — the
    whole spec, through the real resolver, with its family's context."""
    ctx = _CTX_FOR_TEMPLATE[name]()
    for label, template in _text_surfaces(SPECS[name]):
        out = resolver.resolve(template, ctx)
        assert "{" not in out, f"{name} {label}: unresolved token in {out!r}"
        assert "  " not in out, f"{name} {label}: double space in {out!r}"
        assert not out.startswith("the "), f"{name} {label}: uncapitalized article: {out!r}"
        assert " ." not in out and " ," not in out, (
            f"{name} {label}: orphan punctuation in {out!r}"
        )


# --- family registers ------------------------------------------------------


def test_us_pro_register_travel_line(resolver):
    """US pro convention: articled franchises, records, travel line, venue."""
    spec = SPECS["Default Event (Starter)"]
    out = resolver.resolve_conditional(spec["conditional_descriptions"], _nba_ctx())
    assert out == (
        "The 8-4 Detroit Pistons travel to Auburn Hills, MI to play the "
        "10-2 Boston Celtics at The Palace. the Detroit Pistons have won 2 of "
        "their last five; the Boston Celtics have won 4 of their last five. "
        "Series tied 1-1"
    )


def test_soccer_club_register_articleless_face(resolver):
    """Soccer club convention: proper-noun names (never 'the Arsenal'),
    'face' match register."""
    spec = SPECS["Soccer Club Event (Starter)"]
    out = resolver.resolve_conditional(spec["conditional_descriptions"], _soccer_club_ctx())
    assert out.startswith("Arsenal face Chelsea at Stamford Bridge.")
    assert "the Arsenal" not in out and "the Chelsea" not in out


def test_national_register_bare_names_and_year_title(resolver):
    """National teams render bare; tournament title is year-composed."""
    spec = SPECS["International Event (Starter)"]
    ctx = _national_ctx()
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert out.startswith("Belgium face Spain at MetLife Stadium.")
    assert "the Belgium" not in out and "the Spain" not in out
    title = resolver.resolve(spec["title_format"], ctx)
    assert title == "FIFA World Cup 2026"


def test_college_ranked_matchup_leads_with_ranks(resolver):
    spec = SPECS["College Event (Starter)"]
    ctx = _college_ctx(home_rank=20, away_rank=15)
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert out.startswith("No. 20 Arkansas Razorbacks (20-7) host No. 15 Texas A&M Aggies (19-8)")
    assert "Bud Walton Arena" in out


def test_college_unranked_never_shows_rank_prefix(resolver):
    """{*_rank_display} is empty-safe (#354): no orphan 'No. ' ever renders."""
    spec = SPECS["College Event (Starter)"]
    ctx = _college_ctx()  # no ranks
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert "No." not in out
    assert out.startswith("Arkansas Razorbacks (20-7) host Texas A&M Aggies (19-8)")


def test_college_one_ranked_team_shows_only_that_rank(resolver):
    """One-ranked matchups (the common case) show the one rank gracefully —
    previously the both-ranked gate hid ranks entirely (#354)."""
    spec = SPECS["College Event (Starter)"]
    ctx = _college_ctx(home_rank=7)  # away unranked
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert out.startswith("No. 7 Arkansas Razorbacks (20-7) host Texas A&M Aggies (19-8)")
    assert out.count("No.") == 1


def test_college_conference_game_names_the_conference(resolver):
    spec = SPECS["College Team (Starter)"]
    ctx = _college_ctx(conference="Southeastern Conference")
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert "in Southeastern Conference play" in out


def test_provider_preview_short_circuits_construction(resolver):
    """has_preview beats every constructed row (ESPN-copy-first, tvnk.14)."""
    spec = SPECS["Default Event (Starter)"]
    ctx = _nba_ctx(game_preview="Pistons look to even the series in Boston.")
    out = resolver.resolve_conditional(spec["conditional_descriptions"], ctx)
    assert out == "Pistons look to even the series in Boston."


def test_postgame_not_final_reads_coherently(resolver):
    """Postponed/suspended hardening: the not-final line names both sides."""
    spec = SPECS["Default Team (Starter)"]
    ctx = _nba_ctx()
    out = resolver.resolve(spec["postgame_conditional"]["description_not_final"], ctx)
    assert out.startswith("The game between the Boston Celtics and the Detroit Pistons")


def test_combat_title_and_channel_name(resolver):
    """Combat convention: '<Promotion> <number>: <segment>' title register."""
    spec = SPECS["Combat Event (Starter)"]
    ctx = _combat_ctx()
    title = resolver.resolve(spec["title_format"], ctx)
    assert title == "UFC 325: Main Card"
    channel = resolver.resolve(spec["event_channel_name"], ctx)
    assert channel == "UFC 325 Main Card"


def test_tennis_year_prefixed_tournament_title(resolver):
    spec = SPECS["Tennis Event (Starter)"]
    ctx = _tennis_ctx()
    title = resolver.resolve(spec["title_format"], ctx)
    assert title == "2026 Wimbledon"
    # player1 mirrors fighter1 = the away slot (first in ESPN's event title)
    sub = resolver.resolve(spec["subtitle_template"], ctx)
    assert sub == "Final - Jannik Sinner vs Carlos Alcaraz"


def test_milb_titles_as_minor_league_baseball_via_default_event(resolver):
    """End-to-end of the tvnk.12 seed + tvnk.8 branding: MiLB needs no
    dedicated starter (retired in tvnk.4) — Default Event titles every level
    as Gracenote's real 'Minor League Baseball' straight from the seeds."""
    spec = SPECS["Default Event (Starter)"]
    ctx = _milb_ctx()
    title = resolver.resolve(spec["title_format"], ctx)
    assert title == "Minor League Baseball"
    # Channel prefix is the per-level alias ('AAA |'), the more informative form
    channel = resolver.resolve(spec["event_channel_name"], ctx)
    assert channel == "AAA | ABQ/SUG"


def test_soccer_channel_name_uses_v_connector(resolver):
    spec = SPECS["Soccer Club Event (Starter)"]
    channel = resolver.resolve(spec["event_channel_name"], _soccer_club_ctx())
    assert channel.endswith("| ARS v CHE")


def test_event_channel_names_stay_guide_short(resolver):
    """SUPER SHORT constraint: matchup channel names must survive truncating
    guides (~28 chars incl. league prefix)."""
    for name, builder in _CTX_FOR_TEMPLATE.items():
        spec = SPECS[name]
        if spec["template_type"] != "event":
            continue
        out = resolver.resolve(spec["event_channel_name"], builder())
        assert len(out) <= 28, f"{name}: channel name too long: {out!r} ({len(out)})"
