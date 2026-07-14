"""Starter → XMLTV golden snapshots (#375, #355 gap 1).

Pins each starter template's complete end-to-end XMLTV output — the seeded
DB row through template_to_*_config, the real programme generators
(EventEPGGenerator / TeamEPGGenerator), the real filler generators, and
programmes_to_xmltv + merge_xmltv_content — against a stored golden file
with a frozen clock, frozen events, and a pinned timezone. A resolver,
cleanup, condition-selection, seeding, conversion, filler, or XMLTV-writer
regression that subtly changes every guide fails here even when no
convention assertion in test_starter_rendering.py catches it.

Golden files live in tests/templates/goldens/. When output changes on
purpose, regenerate and review the diff like any other code change:

    UPDATE_GOLDENS=1 pytest tests/templates/test_starter_xmltv_goldens.py
"""

import difflib
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.event_epg import EventEPGGenerator, EventEPGOptions
from teamarr.consumers.filler.event_filler import (
    EventFillerGenerator,
    EventFillerOptions,
    template_to_event_filler_config,
)
from teamarr.consumers.team_epg import TeamEPGGenerator, TeamEPGOptions
from teamarr.core.types import Event, EventStatus, RacingSession, Team, TeamStats, Venue
from teamarr.database.default_templates import DEFAULT_TEMPLATE_SET
from teamarr.database.settings import get_all_settings
from teamarr.database.templates import (
    get_template_by_name,
    template_to_event_config,
    template_to_filler_config,
    template_to_programme_config,
)
from teamarr.services import league_mappings as lm
from teamarr.utilities.xmltv import merge_xmltv_content, programmes_to_xmltv

GOLDEN_DIR = Path(__file__).parent / "goldens"

# Frozen clock: 2026-07-10 11:00 EDT (15:00 UTC), 4h before the 19:00 UTC
# family event used across contexts.
TZ_NAME = "America/New_York"
NOW_UTC = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
EVENT_START = datetime(2026, 7, 10, 19, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    """The real LeagueMappingService over the seeded temp DB — gracenote
    categories, aliases, and event_types resolve exactly as in production."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture(autouse=True)
def pinned_timezone():
    """Pin the EPG timezone so <date> tags and filler day math are frozen."""
    from teamarr.config import Config

    prior = Config._timezone_cache
    Config.set_timezone(TZ_NAME)
    yield
    Config._timezone_cache = prior


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Freeze the wall clock in the team EPG/filler windowing paths."""
    frozen = NOW_UTC.astimezone(ZoneInfo(TZ_NAME))
    monkeypatch.setattr("teamarr.consumers.team_epg.now_user", lambda: frozen)
    monkeypatch.setattr("teamarr.consumers.filler.generator.now_user", lambda: frozen)
    # {relative_day}/{days_until} compare game time against the clock
    monkeypatch.setattr("teamarr.templates.variables.datetime.now_user", lambda: frozen)


class FrozenService:
    """SportsDataService stand-in: frozen stats + schedule, no enrichment."""

    def __init__(self, stats=None, schedule=None):
        self._stats = stats or {}
        self._schedule = schedule or []

    def enrich_event_preview(self, event):
        return event

    def refresh_event_status(self, event):
        return event

    def get_team_stats(self, team_id, league):
        return self._stats.get(team_id)

    def get_team_schedule(self, team_id, league, days_ahead=30):
        return list(self._schedule)


# --- frozen events (mirrors test_starter_rendering.py family contexts) ------


def _team(name, abbrev, league, sport, id_="1", short=None):
    return Team(
        id=id_, provider="espn", name=name, short_name=short or name,
        abbreviation=abbrev, league=league, sport=sport,
    )


_VENUE = Venue(name="The Palace", city="Auburn Hills", state="MI")


def _event(home, away, league, sport, *, id_="e1", state="pre",
           start=EVENT_START, venue=_VENUE, **kw):
    return Event(
        id=id_, provider="espn", name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=start, home_team=home, away_team=away,
        status=EventStatus(state=state), league=league, sport=sport,
        venue=venue, **kw,
    )


def _nba_teams():
    home = _team("Boston Celtics", "BOS", "nba", "basketball", "1", short="Celtics")
    away = _team("Detroit Pistons", "DET", "nba", "basketball", "2", short="Pistons")
    return home, away


def _nba_event(**kw):
    home, away = _nba_teams()
    return _event(home, away, "nba", "basketball",
                  home_last_five="4-1", away_last_five="2-3",
                  series_summary="Series tied 1-1", **kw)


NBA_STATS = {"1": TeamStats(record="10-2"), "2": TeamStats(record="8-4")}


def _soccer_teams():
    home = _team("Chelsea", "CHE", "eng.1", "soccer", "1")
    away = _team("Arsenal", "ARS", "eng.1", "soccer", "2")
    return home, away


def _soccer_event(**kw):
    home, away = _soccer_teams()
    return _event(home, away, "eng.1", "soccer",
                  venue=Venue(name="Stamford Bridge", city="London"),
                  home_last_five="3-2", away_last_five="4-1", **kw)


SOCCER_STATS = {"1": TeamStats(record="10-2-5"), "2": TeamStats(record="12-3-2")}


def _college_teams():
    home = _team("Arkansas Razorbacks", "ARK", "mens-college-basketball",
                 "basketball", "1", short="Razorbacks")
    away = _team("Texas A&M Aggies", "TAMU", "mens-college-basketball",
                 "basketball", "2", short="Aggies")
    return home, away


def _college_event(**kw):
    home, away = _college_teams()
    return _event(home, away, "mens-college-basketball", "basketball",
                  venue=Venue(name="Bud Walton Arena", city="Fayetteville", state="AR"),
                  home_last_five="4-1", away_last_five="3-2", **kw)


COLLEGE_STATS = {
    "1": TeamStats(record="20-7", rank=20, conference="Southeastern Conference"),
    "2": TeamStats(record="19-8", rank=15, conference="Southeastern Conference"),
}


def _national_event(**kw):
    home = _team("Spain", "ESP", "fifa.world", "soccer", "1")
    away = _team("Belgium", "BEL", "fifa.world", "soccer", "2")
    return _event(home, away, "fifa.world", "soccer",
                  venue=Venue(name="MetLife Stadium", city="East Rutherford"),
                  home_last_five="4-1", away_last_five="3-2", **kw)


def _combat_event():
    f1 = _team("Alexander Volkanovski", "VOL", "ufc", "mma", "1")
    f2 = _team("Diego Lopes", "LOP", "ufc", "mma", "2")
    start = datetime(2026, 7, 10, 22, 0, tzinfo=UTC)
    main_card = datetime(2026, 7, 11, 1, 0, tzinfo=UTC)
    return Event(
        id="e1", provider="espn", name="UFC 325: Volkanovski vs Lopes",
        short_name="UFC 325", start_time=start, home_team=f1, away_team=f2,
        status=EventStatus(state="pre"), league="ufc", sport="mma",
        venue=Venue(name="T-Mobile Arena", city="Las Vegas"),
        main_card_start=main_card,
        segment_times={"prelims": start, "main_card": main_card},
    )


def _tennis_event(**kw):
    p1 = _team("Carlos Alcaraz", "ALC", "atp", "tennis", "1")
    p2 = _team("Jannik Sinner", "SIN", "atp", "tennis", "2")
    return _event(p1, p2, "atp", "tennis",
                  venue=Venue(name="Centre Court", city="London"),
                  tournament_name="Wimbledon", round_name="Final",
                  draw_type="Men's Singles", is_major=True, **kw)


def _racing_event():
    car = _team("Navy 250", "N250", "nascar-cup", "racing", "1")
    return Event(
        id="e1", provider="nascar", name="Navy 250", short_name="Navy 250",
        start_time=EVENT_START, home_team=car, away_team=car,
        status=EventStatus(state="pre"), league="nascar-cup", sport="racing",
        venue=Venue(name="Nashville Superspeedway", city="Lebanon", state="TN"),
        circuit_name="Nashville Superspeedway",
        sessions=[
            RacingSession(code="fp1", name="Practice 1",
                          start_time=EVENT_START),
            RacingSession(code="qualifying", name="Qualifying",
                          start_time=datetime(2026, 7, 11, 17, 0, tzinfo=UTC)),
            RacingSession(code="race", name="Race",
                          start_time=datetime(2026, 7, 12, 19, 0, tzinfo=UTC)),
        ],
    )


# --- generation paths --------------------------------------------------------


def _sport_durations(conn):
    return asdict(get_all_settings(conn).durations)


def _render_event_starter(conn, name, event, stats=None, *,
                          segment=None, segment_start=None, segment_end=None):
    """Seeded template row → EventEPGGenerator → event filler → XMLTV."""
    template = get_template_by_name(conn, name)
    assert template is not None, f"starter {name!r} not seeded"

    service = FrozenService(stats=stats)
    options = EventEPGOptions(
        template=template_to_event_config(template),
        sport_durations=_sport_durations(conn),
    )
    match = {"stream": {"name": f"{event.name} HD"}, "event": event}
    if segment:
        match.update(segment=segment, segment_start=segment_start,
                     segment_end=segment_end)
    generator = EventEPGGenerator(service)
    programmes, channels = generator.generate_for_matched_streams([match], options)
    assert len(programmes) == 1 and len(channels) == 1

    # Filler exactly as XmltvRenderer._generate_filler_for_streams builds it,
    # with the frozen clock in place of datetime.now().
    if template.pregame_enabled or template.postgame_enabled:
        filler_config = template_to_event_filler_config(template)
        filler_options = EventFillerOptions(
            epg_start=NOW_UTC - timedelta(hours=6),
            epg_end=NOW_UTC + timedelta(days=1),
            epg_timezone=TZ_NAME,
            sport_durations=options.sport_durations,
        )
        use_event = event
        if segment_start and segment_end:
            filler_options = replace(
                filler_options,
                epg_end=segment_end + timedelta(hours=24),
                event_end_override=segment_end,
            )
            use_event = replace(event, start_time=segment_start)
        result = EventFillerGenerator(service).generate_with_counts(
            event=use_event,
            channel_id=channels[0].channel_id,
            config=filler_config,
            options=filler_options,
            card_segment=segment,
        )
        programmes.extend(result.programmes)
        programmes.sort(key=lambda p: (p.channel_id, p.start))

    channel_dicts = [
        {"id": ch.channel_id, "name": ch.name, "icon": ch.icon} for ch in channels
    ]
    return merge_xmltv_content([programmes_to_xmltv(programmes, channel_dicts)])


def _render_team_starter(conn, name, *, schedule, stats,
                         team_id="1", league, team_name, team_abbrev):
    """Seeded template row → TeamEPGGenerator (programmes + filler) → XMLTV."""
    template = get_template_by_name(conn, name)
    assert template is not None, f"starter {name!r} not seeded"

    service = FrozenService(stats=stats, schedule=schedule)
    options = TeamEPGOptions(
        template=template_to_programme_config(template),
        filler_config=template_to_filler_config(template),
        epg_timezone=TZ_NAME,
        output_days_ahead=3,
        lookback_hours=6,
        sport_durations=_sport_durations(conn),
    )
    channel_id = f"teamarr-team-{team_id}"
    programmes = TeamEPGGenerator(service).generate(
        team_id=team_id,
        league=league,
        channel_id=channel_id,
        team_name=team_name,
        team_abbrev=team_abbrev,
        options=options,
    )
    assert programmes, f"{name}: team path generated no programmes"
    channels = [{"id": channel_id, "name": team_name, "icon": None}]
    return merge_xmltv_content([programmes_to_xmltv(programmes, channels)])


def _schedule_around_now(current, *, last_opponent, next_opponent):
    """Last-final / current / next-scheduled triple for .last/.next vars."""
    home = current.home_team
    last = _event(
        home, last_opponent, current.league, current.sport,
        id_="e0", state="final", start=EVENT_START - timedelta(days=2),
        home_score=112, away_score=104,
    )
    nxt = _event(
        home, next_opponent, current.league, current.sport,
        id_="e2", start=EVENT_START + timedelta(days=2),
    )
    return [last, current, nxt]


# --- one case per starter ----------------------------------------------------


def _case_default_event(conn):
    return _render_event_starter(conn, "Default Event (Starter)",
                                 _nba_event(), NBA_STATS)


def _case_college_event(conn):
    return _render_event_starter(conn, "College Event (Starter)",
                                 _college_event(), COLLEGE_STATS)


def _case_soccer_club_event(conn):
    return _render_event_starter(conn, "Soccer Club Event (Starter)",
                                 _soccer_event(), SOCCER_STATS)


def _case_combat_event(conn):
    event = _combat_event()
    return _render_event_starter(
        conn, "Combat Event (Starter)", event,
        segment="main_card",
        segment_start=event.main_card_start,
        segment_end=event.main_card_start + timedelta(hours=3),
    )


def _case_international_event(conn):
    return _render_event_starter(conn, "International Event (Starter)",
                                 _national_event())


def _case_tennis_event(conn):
    return _render_event_starter(conn, "Tennis Event (Starter)", _tennis_event())


def _case_racing_event(conn):
    event = _racing_event()
    return _render_event_starter(
        conn, "Racing Event (Starter)", event,
        segment="fp1",
        segment_start=EVENT_START,
        segment_end=EVENT_START + timedelta(hours=2),
    )


def _case_default_team(conn):
    current = _nba_event()
    bulls = _team("Chicago Bulls", "CHI", "nba", "basketball", "3", short="Bulls")
    knicks = _team("New York Knicks", "NYK", "nba", "basketball", "4", short="Knicks")
    stats = dict(NBA_STATS)
    stats.update({"3": TeamStats(record="6-6"), "4": TeamStats(record="7-5")})
    return _render_team_starter(
        conn, "Default Team (Starter)",
        schedule=_schedule_around_now(current, last_opponent=knicks,
                                      next_opponent=bulls),
        stats=stats, league="nba",
        team_name="Boston Celtics", team_abbrev="BOS",
    )


def _case_soccer_team(conn):
    current = _soccer_event()
    spurs = _team("Tottenham Hotspur", "TOT", "eng.1", "soccer", "3")
    liverpool = _team("Liverpool", "LIV", "eng.1", "soccer", "4")
    stats = dict(SOCCER_STATS)
    stats.update({"3": TeamStats(record="9-4-4"), "4": TeamStats(record="13-2-2")})
    return _render_team_starter(
        conn, "Soccer Team (Starter)",
        schedule=_schedule_around_now(current, last_opponent=spurs,
                                      next_opponent=liverpool),
        stats=stats, league="eng.1",
        team_name="Chelsea", team_abbrev="CHE",
    )


def _case_college_team(conn):
    current = _college_event()
    lsu = _team("LSU Tigers", "LSU", "mens-college-basketball",
                "basketball", "3", short="Tigers")
    kentucky = _team("Kentucky Wildcats", "UK", "mens-college-basketball",
                     "basketball", "4", short="Wildcats")
    stats = dict(COLLEGE_STATS)
    stats.update({
        "3": TeamStats(record="15-12", conference="Southeastern Conference"),
        "4": TeamStats(record="21-6", rank=8, conference="Southeastern Conference"),
    })
    return _render_team_starter(
        conn, "College Team (Starter)",
        schedule=_schedule_around_now(current, last_opponent=lsu,
                                      next_opponent=kentucky),
        stats=stats, league="mens-college-basketball",
        team_name="Arkansas Razorbacks", team_abbrev="ARK",
    )


CASES = {
    "Default Team (Starter)": _case_default_team,
    "Soccer Team (Starter)": _case_soccer_team,
    "College Team (Starter)": _case_college_team,
    "Default Event (Starter)": _case_default_event,
    "College Event (Starter)": _case_college_event,
    "Soccer Club Event (Starter)": _case_soccer_club_event,
    "Combat Event (Starter)": _case_combat_event,
    "International Event (Starter)": _case_international_event,
    "Tennis Event (Starter)": _case_tennis_event,
    "Racing Event (Starter)": _case_racing_event,
}


def _slug(name):
    return name.removesuffix(" (Starter)").lower().replace(" ", "_")


def _assert_matches_golden(name, content):
    path = GOLDEN_DIR / f"{_slug(name)}.xml"
    actual = content + "\n"
    if os.environ.get("UPDATE_GOLDENS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual)
        return
    assert path.exists(), (
        f"missing golden {path.name} — generate with "
        f"UPDATE_GOLDENS=1 pytest {Path(__file__).name}"
    )
    expected = path.read_text()
    if actual != expected:
        diff = "\n".join(difflib.unified_diff(
            expected.splitlines(), actual.splitlines(),
            fromfile=f"goldens/{path.name}", tofile="generated", lineterm="",
        ))
        pytest.fail(
            f"XMLTV output changed for {name}:\n{diff}\n\n"
            f"If this change is intentional, regenerate with "
            f"UPDATE_GOLDENS=1 pytest tests/templates/test_starter_xmltv_goldens.py "
            f"and review the golden diff."
        )


@pytest.mark.parametrize("name", sorted(CASES))
def test_starter_xmltv_matches_golden(name, db_conn):
    _assert_matches_golden(name, CASES[name](db_conn))


def test_every_starter_has_a_golden_case():
    """Adding/renaming a starter must add/rename its golden case too."""
    assert set(CASES) == {spec["name"] for spec in DEFAULT_TEMPLATE_SET}
