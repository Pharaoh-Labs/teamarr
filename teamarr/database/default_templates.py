"""Curated default template set (epic teamarrv2-tvnk, issue #329).

Gracenote-modeled defaults, seeded UNASSIGNED — the user scopes them (see
docs/guide/templates/defaults.md for the recommended scoping table). Design
decisions (bead tvnk.1, 2026-07-09):

- REPLACE the legacy 2 generic seeds: a pristine legacy "Team"/"Event" row
  (content fingerprint: stock title, subtitle, art in either historical form,
  and stock default description) is upgraded IN PLACE — same row id, so
  template assignments and group references survive. A user-modified legacy
  row is never touched; the curated set is simply added alongside.
- Seed on fresh installs AND upgrades: any set member missing by name is
  added on startup; existing rows are never overwritten.
- Art ships as RELATIVE paths (variable-led, slash-less per #275) prefixed
  by the art_base_url setting at render time (epic z02s) — this also retires
  the localhost:3000 placeholder (bead tvnk.2).
- SUPER SHORT channel titles are a first-class constraint: client guides
  truncate channel names aggressively (~15-20 visible chars), so every event
  template's ``event_channel_name`` is abbreviation-first with no filler.
"""

from sqlite3 import Connection

# Relative art paths (z02s): prefixed with the art_base_url setting at render.
# Variable-led values stay slash-less — a leading variable may resolve to an
# absolute URL, and a prepended "/" would break it (#275).
#
# Query params follow the game-thumbs conventions (inferred from sethwv's
# server, tvnk.1 decision b): style=1 for team covers, style=6 for event
# matchup covers, logo=true overlays team logos, fallback=true serves generic
# art when a matchup image is missing. Event CHANNEL logos carry a badge=
# overlay showing the broadcast network + quality keyword ("ESPN 4K") right
# on the channel icon.
_TEAM_PARAMS = "?style=1&logo=true&fallback=true"
_EVENT_PARAMS = "?style=6&logo=true&fallback=true"
_ART_PATH = "{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"
_TEAM_ART = _ART_PATH + _TEAM_PARAMS
_EVENT_ART = _ART_PATH + _EVENT_PARAMS
_ART_NEXT = "{league_id}/{away_team_pascal.next}/{home_team_pascal.next}/cover.png" + _TEAM_PARAMS
_ART_LAST = "{league_id}/{away_team_pascal.last}/{home_team_pascal.last}/cover.png" + _TEAM_PARAMS
_EVENT_LOGO = (
    "{league_id}/{away_team_pascal}/{home_team_pascal}/logo.png"
    "?style=1&logo=true&fallback=true"
    "&badge={broadcast_national_network}%20{exception_keyword}"
)

_XMLTV_FLAGS = {"new": True, "live": True, "date": True}
_XMLTV_VIDEO = {"enabled": False, "quality": "HDTV"}

# Legacy seeds shipped with this placeholder art. Migration v75 (z02s) later
# stripped the origin into the art_base_url setting, so upgraded installs
# carry the RELATIVE form instead — pristine detection accepts both.
LEGACY_PRISTINE_MARKER = "http://localhost:3000/"
_LEGACY_STRIPPED_ART = "{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"

# Legacy seed name → curated replacement name (upgrade-in-place keeps the row
# id, so assignments and group references survive the rename).
LEGACY_UPGRADES = {"Team": "Default Team", "Event": "Default Event"}

# Content fingerprint of the stock legacy seeds — a row is "pristine" (safe to
# upgrade in place) only when title, subtitle, art AND the default description
# all still match what the seed shipped with. Any user edit to any of them
# leaves the row untouched.
_STOCK_TITLE = "{gracenote_category}"
_STOCK_SUBTITLE = "{away_team} at {home_team}"
_LEGACY_STOCK_CONDITIONAL = {
    "Team": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to take on the {home_team_record} {home_team} at {venue}."
    ),
    "Event": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to play the {home_team_record} {home_team} at {venue}."
    ),
}


def _is_pristine_legacy(row, legacy_name: str) -> bool:
    """True when a legacy seed row still matches its shipped content."""
    if row.title_format != _STOCK_TITLE:
        return False
    if (row.subtitle_template or "") != _STOCK_SUBTITLE:
        return False
    art = row.program_art_url or ""
    stock_art = (
        art.startswith(LEGACY_PRISTINE_MARKER)
        or art == _LEGACY_STRIPPED_ART
        # v75-stripped form with game-thumbs query params (?style=…) — still
        # the stock art pipeline, just parameterized (tvnk.1 decision b).
        or art.startswith(_LEGACY_STRIPPED_ART + "?")
    )
    if not stock_art:
        return False
    conds = row.conditional_descriptions or []
    texts = [c.get("template") for c in conds if isinstance(c, dict)]
    return texts == [_LEGACY_STOCK_CONDITIONAL[legacy_name]]


def _is_unedited_curated(row, spec: dict) -> bool:
    """True when a curated-set row still matches its seeded content.

    Used to heal the transitional state where an earlier seeding pass added a
    curated row alongside a pristine legacy one (before parameterized art
    counted as pristine): the untouched curated duplicate can be folded back
    so the legacy row — which holds the references — upgrades in place.
    Art matches the current spec or its bare (param-less) earlier form.
    """
    if row.title_format != spec.get("title_format"):
        return False
    if (row.subtitle_template or "") != (spec.get("subtitle_template") or ""):
        return False
    if (row.event_channel_name or "") != (spec.get("event_channel_name") or ""):
        return False
    art = row.program_art_url or ""
    spec_art = spec.get("program_art_url") or ""
    bare = spec_art.split("?")[0]
    return art in (spec_art, bare)


def _team_default() -> dict:
    """Universal team-channel fallback (persistent team channels)."""
    return {
        "name": "Default Team",
        "template_type": "team",
        "title_format": "{gracenote_category}",
        "subtitle_template": "{away_team} at {home_team}",
        "program_art_url": _TEAM_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": True,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sports Event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time.next}",
            "subtitle": "{away_team.next} at {home_team.next}",
            "description": (
                "The {away_team_record.next} {away_team.next} travel to "
                "{venue_city.next}, {venue_state.next} to play the "
                "{home_team_record.next} {home_team.next} {today_tonight.next} "
                "at {game_time.next}."
            ),
            "art_url": _ART_NEXT,
        },
        "postgame_periods": [],
        "postgame_fallback": {
            "title": "{gracenote_category}: {team_name} Postgame",
            "subtitle": "{away_team.last} at {home_team.last}",
            "description": "{team_name} {result_text.last} the {opponent.last} {final_score.last}",
            "art_url": _ART_LAST,
        },
        "postgame_conditional": {
            "enabled": True,
            "description_final": (
                "The {team_name} {result_text.last} the {opponent.last} "
                "{final_score.last} {overtime_text.last}"
            ),
            "description_not_final": (
                "The game between the {team_name} and the {opponent.last} on "
                "{game_date.last} has not yet ended as of the last update."
            ),
        },
        "idle_content": {
            "title": "No {team_name} Game Today",
            "subtitle": (
                "Next game: {game_date.next} at {game_time.next} {vs_at.next} the {opponent.next}"
            ),
            "description": "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
            "art_url": "",
        },
        "idle_conditional": {
            "enabled": True,
            "description_final": (
                "The {team_name} {result_text.last} the {opponent.last} "
                "{final_score.last} {overtime_text.last} on {game_date.last}. "
                "Next game will be with the {opponent.next} on {game_date.next}"
            ),
            "description_not_final": (
                "The {team_name} last played against the {opponent.last} on {game_date.last}."
            ),
        },
        "idle_offseason": {
            "title_enabled": False,
            "title": None,
            "subtitle_enabled": True,
            "subtitle": "No upcoming game currently on schedule in next 30 days",
            "description_enabled": True,
            "description": "No upcoming {team_name} games scheduled.",
        },
        "conditional_descriptions": [
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to take on the {home_team_record} {home_team} at {venue}."
                ),
                "priority": 100,
                "label": "Default",
            }
        ],
        "event_channel_name": "{team_name}",
        "event_channel_logo_url": "",
    }


def _event_base(**overrides) -> dict:
    """Shared skeleton for the event templates; variants override fields."""
    base = {
        "template_type": "event",
        "title_format": "{gracenote_category}",
        "subtitle_template": "{away_team} at {home_team}",
        "program_art_url": _EVENT_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": False,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sporting Event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time}",
            "subtitle": "{away_team} at {home_team}",
            "description": (
                "The {away_team_record} {away_team} travel to {venue_city}, "
                "{venue_state} to play the {home_team_record} {home_team} "
                "{today_tonight} at {game_time}."
            ),
            "art_url": _EVENT_ART,
        },
        "postgame_periods": [],
        "postgame_fallback": {
            "title": "{gracenote_category}: Postgame",
            "subtitle": "{away_team} at {home_team}",
            "description": "{game_recap}",
            "art_url": _EVENT_ART,
        },
        "postgame_conditional": {
            "enabled": True,
            "description_final": (
                "The {team_name} {result_text} the {opponent} {final_score} {overtime_text}"
            ),
            "description_not_final": (
                "The game between the {away_team} and {home_team} has not yet "
                "ended as of the last update."
            ),
        },
        "idle_content": {
            "title": "{team_name} Programming",
            "subtitle": "",
            "description": "",
            "art_url": "",
        },
        "idle_conditional": {
            "enabled": False,
            "description_final": "",
            "description_not_final": "",
        },
        "idle_offseason": {
            "title_enabled": False,
            "title": None,
            "subtitle_enabled": False,
            "subtitle": "",
            "description_enabled": False,
            "description": "",
        },
        "conditional_descriptions": [
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to play the {home_team_record} {home_team} at {venue}."
                ),
                "priority": 100,
                "label": "Default",
            }
        ],
        # SUPER SHORT: "NBA | DET/LAL" — abbrev-first, fits truncating guides.
        "event_channel_name": "{league} | {away_team_abbrev}/{home_team_abbrev}",
        "event_channel_logo_url": _EVENT_LOGO,
    }
    base.update(overrides)
    return base


DEFAULT_TEMPLATE_SET: list[dict] = [
    _team_default(),
    # Universal event fallback — US pro leagues with abbreviations.
    _event_base(name="Default Event"),
    # Combat (MMA/boxing): card-segment channels, event-number titles.
    _event_base(
        name="Combat Event",
        title_format="{league} {event_number}: {card_segment_display}",
        subtitle_template="{away_team} vs {home_team}",
        pregame_fallback={
            "title": "Coming up: {league} {event_number} at {game_time}",
            "subtitle": "{away_team} vs {home_team}",
            "description": (
                "{away_team} takes on {home_team} at {venue} {today_tonight} at {game_time}."
            ),
            "art_url": _EVENT_ART,
        },
        conditional_descriptions=[
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team} takes on {home_team} at {venue}.",
                "priority": 100,
                "label": "Default",
            }
        ],
        # "UFC 310 Main Card"
        event_channel_name="{league} {event_number} {card_segment_display}",
    ),
    # International (national teams / tournaments): category-led naming.
    _event_base(
        name="International Event",
        title_format="{gracenote_category}",
        subtitle_template="{away_team} vs {home_team}",
        # "NED v JPN"
        event_channel_name="{away_team_abbrev} v {home_team_abbrev}",
        conditional_descriptions=[
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team} face {home_team} at {venue}.",
                "priority": 100,
                "label": "Default",
            }
        ],
    ),
    # Leagues without abbreviations: full names everywhere.
    _event_base(
        name="No-Abbrev Event",
        event_channel_name="{away_team} / {home_team}",
    ),
    # Minor-league baseball: explicit MiLB branding (league var is the level).
    _event_base(
        name="MiLB Event",
        event_channel_name="MiLB | {away_team_abbrev}/{home_team_abbrev}",
    ),
    # Tennis (bead tvnk.13): tournament-led titles, player-surname channels.
    _event_base(
        name="Tennis Event",
        title_format="{tournament_name}",
        subtitle_template="{tennis_round} - {player1} vs {player2}",
        pregame_fallback={
            "title": "Coming up: {tournament_name} at {game_time}",
            "subtitle": "{player1} vs {player2}",
            "description": (
                "{player1} takes on {player2} in the {tennis_round} of the "
                "{tournament_name} ({tennis_draw})."
            ),
            "art_url": _EVENT_ART,
        },
        postgame_fallback={
            "title": "{tournament_name}: Match Complete",
            "subtitle": "{player1} vs {player2}",
            "description": "{game_recap}",
            "art_url": _EVENT_ART,
        },
        postgame_conditional={
            "enabled": True,
            "description_final": "{game_recap}",
            "description_not_final": (
                "The match between {player1} and {player2} has not yet ended as of the last update."
            ),
        },
        conditional_descriptions=[
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "{player1} takes on {player2} in the {tennis_round} of the "
                    "{tournament_name} ({tennis_draw})."
                ),
                "priority": 100,
                "label": "Default",
            }
        ],
        # "Alcaraz v Sinner" — surnames only, super short.
        event_channel_name="{player1_last} v {player2_last}",
    ),
]


def seed_default_templates(conn: Connection) -> None:
    """Seed the curated default set — idempotent, safe on every startup.

    1. A PRISTINE legacy seed ("Team"/"Event" still carrying the broken
       localhost:3000 placeholder art) is upgraded in place to its curated
       replacement — same row id, so assignments survive (tvnk.1 decision).
    2. Any set member missing by name is created (fresh installs get all 7;
       upgrades pick up new members). Existing rows are NEVER overwritten.
    """
    from teamarr.database.templates import (
        create_template,
        delete_template,
        get_all_templates,
        update_template,
    )

    existing = {t.name: t for t in get_all_templates(conn)}
    specs = {spec["name"]: spec for spec in DEFAULT_TEMPLATE_SET}

    # 1. Upgrade pristine legacy seeds in place (keeps ids/assignments).
    for legacy_name, curated_name in LEGACY_UPGRADES.items():
        row = existing.get(legacy_name)
        if row is None or not _is_pristine_legacy(row, legacy_name):
            continue  # absent or user-modified — curated added below if missing
        dup = existing.get(curated_name)
        if dup is not None:
            # Transitional healing: an earlier pass seeded the curated row
            # alongside this pristine legacy one. If that duplicate is still
            # untouched, fold it back so the legacy row (which holds the
            # references) becomes the curated one; otherwise leave both.
            if not _is_unedited_curated(dup, specs[curated_name]):
                continue
            delete_template(conn, dup.id)
            del existing[curated_name]
        spec = dict(specs[curated_name])
        update_template(conn, row.id, **spec)
        existing[curated_name] = existing.pop(legacy_name)

    # 2. Add missing set members.
    for name, spec in specs.items():
        if name in existing:
            continue
        create_template(conn, **spec)
