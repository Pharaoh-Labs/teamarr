"""A cleared template text field stays cleared (#1063).

The editor saves a blank title/subtitle/description as NULL. The row loader
used to substitute the original hardcoded defaults (``{venue_full}`` for the
subtitle, ``{matchup} | {venue_full}`` for the description, the team-shaped
``{team_name} {sport}`` for the title), so a user who blanked the subtitle saw
it filled back in on the next read and in the generated guide.
"""

from teamarr.database.templates import (
    create_template,
    get_template,
    template_to_event_config,
    template_to_programme_config,
    update_template,
)


def test_new_template_keeps_schema_defaults(db_conn):
    tid = create_template(db_conn, "fresh", template_type="event")
    t = get_template(db_conn, tid)
    assert t.subtitle_template == "{venue_full}"
    assert t.description_template == "{matchup} | {venue_full}"


def test_blanked_fields_read_back_blank(db_conn):
    tid = create_template(db_conn, "blanked", template_type="event")
    update_template(
        db_conn,
        tid,
        title_format="{league}",
        subtitle_template=None,
        description_template="",
    )
    t = get_template(db_conn, tid)
    assert t.subtitle_template == ""
    assert t.description_template == ""
    assert t.title_format == "{league}"
    # The converters see the blank too, so generation emits no subtitle/desc.
    assert template_to_event_config(t).subtitle_format == ""
    assert template_to_programme_config(t).description_format == ""
