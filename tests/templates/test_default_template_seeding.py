"""Curated default template seeding (tvnk.1/tvnk.3/tvnk.13, #329).

Fresh installs get the full starter set; upgrades add missing members by
name; a PRISTINE legacy seed (still carrying the broken localhost:3000
placeholder art) is upgraded in place (same row id → assignments survive);
user-modified rows are never touched.
"""

import re

from teamarr.database.default_templates import (
    DEFAULT_TEMPLATE_SET,
    LEGACY_PRISTINE_MARKER,
    seed_default_templates,
)
from teamarr.database.templates import create_template, get_all_templates

SET_NAMES = {spec["name"] for spec in DEFAULT_TEMPLATE_SET}

_STOCK_CONDITIONALS = {
    "Team": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to take on the {home_team_record} {home_team} at {venue}."
    ),
    "Event": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to play the {home_team_record} {home_team} at {venue}."
    ),
}


def _create_stock_legacy(conn, name, art=None):
    """A legacy seed row exactly as old installs carry it (post-v75 art form)."""
    return create_template(
        conn,
        name=name,
        template_type="team" if name == "Team" else "event",
        title_format="{gracenote_category}",
        subtitle_template="{away_team} at {home_team}",
        program_art_url=art or "{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png",
        conditional_descriptions=[
            {
                "condition": None,
                "condition_value": None,
                "template": _STOCK_CONDITIONALS[name],
                "priority": 100,
                "label": "Default",
            }
        ],
    )


def _names(conn):
    return {t.name for t in get_all_templates(conn)}


def test_fresh_install_seeds_full_set(db_conn):
    # init_db already seeded (the wiring under test); re-run is a no-op
    seed_default_templates(db_conn)
    assert _names(db_conn) == SET_NAMES
    assert len(SET_NAMES) == 10

    for t in get_all_templates(db_conn):
        # Seeded UNASSIGNED — the user scopes them
        assert t.sport is None and t.league is None
        # Relative art (z02s) — the localhost placeholder is retired (tvnk.2).
        # Variable-led values are canonically slash-less (#275).
        assert not (t.program_art_url or "").startswith("http")
        assert (t.program_art_url or "{").startswith("{")


def test_fresh_install_starters_are_immediately_assignable(db_conn):
    """First-run UX (tvnk.4): a brand-new install can scope a starter to a
    league and have it resolve for that league's events with no other setup."""
    from teamarr.database.subscription import (
        add_subscription_template,
        get_subscription_template_for_event,
    )

    templates = {t.name: t for t in get_all_templates(db_conn)}
    starter_id = templates["Soccer Club Event (Starter)"].id
    add_subscription_template(db_conn, template_id=starter_id, leagues=["eng.1"])
    assert get_subscription_template_for_event(db_conn, "soccer", "eng.1") == starter_id


def test_seeding_is_idempotent(db_conn):
    seed_default_templates(db_conn)
    ids_before = {t.name: t.id for t in get_all_templates(db_conn)}
    seed_default_templates(db_conn)
    ids_after = {t.name: t.id for t in get_all_templates(db_conn)}
    assert ids_before == ids_after


def test_pristine_legacy_seed_upgraded_in_place(db_conn):
    # Simulate an old install: wipe the fixture's seeds (init_db now seeds),
    # leaving only a legacy "Event" seed with the placeholder art
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    legacy_id = _create_stock_legacy(db_conn, "Event")

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert "Event" not in templates  # renamed, not duplicated
    upgraded = templates["Default Event (Starter)"]
    assert upgraded.id == legacy_id  # same row → assignments survive
    assert (upgraded.program_art_url or "").startswith("{")
    assert _names(db_conn) == SET_NAMES


def test_pristine_legacy_with_localhost_art_also_upgrades(db_conn):
    """Pre-v75 installs still carry the localhost placeholder art."""
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    legacy_id = _create_stock_legacy(
        db_conn, "Team", art=LEGACY_PRISTINE_MARKER + "{league_id}/cover.png"
    )
    seed_default_templates(db_conn)
    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert templates["Default Team (Starter)"].id == legacy_id
    assert _names(db_conn) == SET_NAMES


def test_modified_legacy_seed_left_untouched(db_conn):
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    # User customized their "Team" template (title no longer stock)
    modified_id = create_template(
        db_conn,
        name="Team",
        template_type="team",
        title_format="My Custom Title",
        program_art_url="https://my.cdn/art/{league_id}.png",
    )

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    kept = templates["Team"]
    assert kept.id == modified_id
    assert kept.title_format == "My Custom Title"
    assert kept.program_art_url == "https://my.cdn/art/{league_id}.png"
    # Curated set added alongside
    assert _names(db_conn) == SET_NAMES | {"Team"}


def test_upgrade_adds_missing_members_only(db_conn):
    seed_default_templates(db_conn)
    # User deletes one, modifies another
    templates = {t.name: t for t in get_all_templates(db_conn)}
    from teamarr.database.templates import delete_template, update_template

    delete_template(db_conn, templates["Combat Event (Starter)"].id)
    update_template(db_conn, templates["Tennis Event (Starter)"].id, title_format="Custom Tennis")

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert "Combat Event (Starter)" in templates  # re-added (missing by name)
    assert templates["Tennis Event (Starter)"].title_format == "Custom Tennis"  # untouched


_VAR_TOKEN = re.compile(r"\{([a-z0-9_]+)(?:\.(?:next|last))?\}")


def _collect_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _collect_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _collect_strings(v)


def test_every_template_variable_is_registered():
    """Guard against typo'd/invented variables in the curated set."""
    import teamarr.templates.variables  # noqa: F401 — triggers registration
    from teamarr.templates.variables import registry as reg_module

    registry = reg_module.VariableRegistry()
    known = {v.name for v in registry.all_variables()}
    assert known, "variable registry unexpectedly empty"

    unknown: set[str] = set()
    for spec in DEFAULT_TEMPLATE_SET:
        for text in _collect_strings(spec):
            for m in _VAR_TOKEN.finditer(text):
                if m.group(1) not in known:
                    unknown.add(m.group(1))
    assert not unknown, f"unregistered template variables used: {sorted(unknown)}"


def test_parameterized_stock_art_counts_as_pristine(db_conn):
    """Stock rows whose art carries game-thumbs query params still upgrade."""
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    legacy_id = _create_stock_legacy(
        db_conn,
        "Event",
        art="{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"
        "?style=6&logo=true&fallback=true",
    )
    seed_default_templates(db_conn)
    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert templates["Default Event (Starter)"].id == legacy_id
    assert _names(db_conn) == SET_NAMES


def test_healing_folds_unedited_curated_duplicate_into_legacy(db_conn):
    """Transitional state: pristine legacy + freshly-seeded curated duplicate.

    The untouched duplicate is deleted and the legacy row (which holds all
    the references) upgrades in place under the curated name.
    """
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    legacy_id = _create_stock_legacy(
        db_conn,
        "Event",
        art="{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"
        "?style=6&logo=true&fallback=true",
    )
    # Simulate the earlier pass: full set seeded alongside (param-less art era
    # is covered by _is_unedited_curated's bare-art acceptance).
    for spec in DEFAULT_TEMPLATE_SET:
        create_template(db_conn, **spec)

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert _names(db_conn) == SET_NAMES  # duplicate folded, 7 total
    assert templates["Default Event (Starter)"].id == legacy_id  # legacy row won


def test_edited_curated_duplicate_is_not_folded(db_conn):
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    _create_stock_legacy(
        db_conn,
        "Event",
        art="{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"
        "?style=6&logo=true&fallback=true",
    )
    for spec in DEFAULT_TEMPLATE_SET:
        create_template(db_conn, **spec)
    from teamarr.database.templates import update_template

    templates = {t.name: t for t in get_all_templates(db_conn)}
    update_template(db_conn, templates["Default Event (Starter)"].id, title_format="Edited")

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    # Both survive: user's edit is sacred, legacy left alone
    assert "Event" in templates and "Default Event (Starter)" in templates
    assert templates["Default Event (Starter)"].title_format == "Edited"


def test_prior_iteration_names_renamed_in_place(db_conn):
    """Rows seeded by the first curated iteration (no parenthetical) get the
    (Starter) name on the same row id when unedited."""
    from teamarr.database.default_templates import PRIOR_NAME_UPGRADES

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    # Simulate the prior iteration: same specs, prior names (tvnk.8 members
    # postdate the rename era and have no prior name)
    prior_ids = {}
    for spec in DEFAULT_TEMPLATE_SET:
        prior_name = next((p for p, c in PRIOR_NAME_UPGRADES.items() if c == spec["name"]), None)
        if prior_name is None:
            continue
        prior = dict(spec)
        prior["name"] = prior_name
        prior_ids[spec["name"]] = create_template(db_conn, **prior)
    assert prior_ids, "no prior-iteration members simulated"

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert _names(db_conn) == SET_NAMES
    for current, tid in prior_ids.items():
        assert templates[current].id == tid  # renamed in place


def test_prior_title_upgraded_in_place_when_unedited(db_conn):
    """tvnk.8: unedited rows still carrying a prior-iteration title get the
    current content on the same row id (year-composed tournament titles)."""
    from teamarr.database.default_templates import PRIOR_TITLE_UPGRADES

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    specs = {s["name"]: s for s in DEFAULT_TEMPLATE_SET}
    old_ids = {}
    for member, old_title in PRIOR_TITLE_UPGRADES.items():
        old = dict(specs[member])
        old["title_format"] = old_title
        old_ids[member] = create_template(db_conn, **old)

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    for member, tid in old_ids.items():
        assert templates[member].id == tid  # upgraded in place, not duplicated
        assert templates[member].title_format == specs[member]["title_format"]
    assert _names(db_conn) == SET_NAMES


def test_prior_title_row_with_user_edit_left_alone(db_conn):
    from teamarr.database.default_templates import PRIOR_TITLE_UPGRADES
    from teamarr.database.templates import update_template

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    specs = {s["name"]: s for s in DEFAULT_TEMPLATE_SET}
    member, old_title = next(iter(PRIOR_TITLE_UPGRADES.items()))
    old = dict(specs[member])
    old["title_format"] = old_title
    tid = create_template(db_conn, **old)
    update_template(db_conn, tid, subtitle_template="My custom subtitle")

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert templates[member].id == tid
    assert templates[member].title_format == old_title  # untouched
    assert templates[member].subtitle_template == "My custom subtitle"


def test_prior_name_with_prior_title_renamed_and_upgraded(db_conn):
    """A pre-tvnk.8 install: 'International Event' (no Starter suffix) with
    the old title renames AND upgrades on the same row id."""
    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    specs = {s["name"]: s for s in DEFAULT_TEMPLATE_SET}
    old = dict(specs["International Event (Starter)"])
    old["name"] = "International Event"
    old["title_format"] = "{gracenote_category}"
    tid = create_template(db_conn, **old)

    seed_default_templates(db_conn)

    templates = {t.name: t for t in get_all_templates(db_conn)}
    assert "International Event" not in templates
    upgraded = templates["International Event (Starter)"]
    assert upgraded.id == tid
    assert upgraded.title_format == "{gracenote_category} {year}"
    assert _names(db_conn) == SET_NAMES


def test_retired_no_abbrev_member_removed_when_unedited(db_conn):
    from teamarr.database.default_templates import _retired_no_abbrev_spec

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    create_template(db_conn, **_retired_no_abbrev_spec())

    seed_default_templates(db_conn)
    assert _names(db_conn) == SET_NAMES  # retired member gone, set complete


def test_retired_member_kept_when_edited(db_conn):
    from teamarr.database.default_templates import _retired_no_abbrev_spec
    from teamarr.database.templates import update_template

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    tid = create_template(db_conn, **_retired_no_abbrev_spec())
    update_template(db_conn, tid, title_format="I use this")

    seed_default_templates(db_conn)
    assert "No-Abbrev Event" in _names(db_conn)  # user's row survives


def test_retired_milb_member_removed_when_unedited_and_unassigned(db_conn):
    """MiLB Event retired in tvnk.4 — the 'Minor League Baseball' branding now
    comes from the gracenote_category seeds, so Default Event covers MiLB."""
    from teamarr.database.default_templates import _retired_milb_specs

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    for spec in _retired_milb_specs():
        create_template(db_conn, **spec)

    seed_default_templates(db_conn)
    names = _names(db_conn)
    assert "MiLB Event (Starter)" not in names
    assert "MiLB Event" not in names
    assert names == SET_NAMES


def test_retired_member_kept_when_assigned(db_conn):
    """A retired starter someone ASSIGNED is never auto-deleted — removal
    would silently unassign their channels (SET NULL / CASCADE FKs)."""
    from teamarr.database.default_templates import _retired_milb_specs
    from teamarr.database.subscription import add_subscription_template

    db_conn.execute("DELETE FROM templates")
    db_conn.commit()
    spec = _retired_milb_specs()[0]
    tid = create_template(db_conn, **spec)
    add_subscription_template(db_conn, template_id=tid, leagues=["milb-aaa"])

    seed_default_templates(db_conn)
    assert "MiLB Event (Starter)" in _names(db_conn)  # assignment protected it


def test_abbrev_variables_fall_back_without_abbreviation():
    """*_team_abbrev render short/full names for leagues without abbrevs —
    the reason the No-Abbrev variant could retire (#329)."""
    from datetime import UTC, datetime

    from teamarr.core import Event, EventStatus, Team
    from teamarr.templates.context import GameContext, TemplateContext
    from teamarr.templates.variables.home_away import (
        extract_away_team_abbrev,
        extract_home_team_abbrev,
    )

    def team(name, short, abbrev):
        return Team(
            id="t",
            provider="espn",
            name=name,
            short_name=short,
            abbreviation=abbrev,
            league="epl",
            sport="soccer",
        )

    e = Event(
        id="e1",
        provider="espn",
        name="x",
        short_name="x",
        start_time=datetime(2026, 7, 9, tzinfo=UTC),
        home_team=team("Manchester United", "Man United", ""),
        away_team=team("Arsenal", "Arsenal", "ARS"),
        status=EventStatus(state="scheduled"),
        league="epl",
        sport="soccer",
    )
    ctx = TemplateContext(game_context=GameContext(event=e), team_config=None, team_stats=None)
    assert extract_home_team_abbrev(ctx, ctx.game_context) == "Man United"
    assert extract_away_team_abbrev(ctx, ctx.game_context) == "ARS"


def test_seed_variables_respect_template_scope():
    """Every variable a seed uses must be visible in that template type's
    picker/validator (#354) — a TEAM_ONLY var in an event seed makes the
    builder's real-time validation flag our own shipped content."""
    import teamarr.templates.variables  # noqa: F401 — triggers registration
    from teamarr.templates.variables import registry as reg_module

    registry = reg_module.VariableRegistry()
    by_scope = {
        "team": {v.name for v in registry.filter_by_template_type("team")},
        "event": {v.name for v in registry.filter_by_template_type("event")},
    }
    violations = []
    for spec in DEFAULT_TEMPLATE_SET:
        allowed = by_scope[spec["template_type"]]
        for text in _collect_strings(spec):
            for m in _VAR_TOKEN.finditer(text):
                if m.group(1) not in allowed:
                    violations.append((spec["name"], m.group(1)))
    assert not violations, f"scope-invalid variables in seeds: {sorted(set(violations))}"
