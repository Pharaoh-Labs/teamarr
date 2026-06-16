"""Tests for the v75 game-thumbs base URL migration (epic z02s).

Verifies _migrate_v75_extract_art_base_url:
- extracts a single shared origin and rewrites template art to leading-slash paths
- leaves URLs absolute when templates span multiple origins (ambiguous)
- is idempotent and a no-op when already configured
- and the apply_art_base_url resolver helper round-trips with the stored form.
"""

import json
import sqlite3

import pytest

from teamarr.database.connection import _migrate_v75_extract_art_base_url
from teamarr.utilities.xmltv import apply_art_base_url


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, art_base_url TEXT DEFAULT '')")
    conn.execute("INSERT INTO settings (id, art_base_url) VALUES (1, '')")
    conn.execute(
        """CREATE TABLE templates (
            id INTEGER PRIMARY KEY,
            program_art_url TEXT,
            event_channel_logo_url TEXT,
            pregame_fallback TEXT,
            postgame_fallback TEXT,
            idle_content TEXT
        )"""
    )
    return conn


def test_single_origin_extracted_and_paths_relativized():
    conn = _make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url, "
        "pregame_fallback, postgame_fallback, idle_content) VALUES (1, ?, ?, ?, ?, ?)",
        (
            "http://localhost:3000/{league}/cover.png",
            "http://localhost:3000/logo.png",
            json.dumps({"art_url": "http://localhost:3000/pre.png"}),
            json.dumps({"art_url": None}),
            json.dumps({"title": "x"}),
        ),
    )

    _migrate_v75_extract_art_base_url(conn)

    base = conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
    assert base == "http://localhost:3000"
    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "/{league}/cover.png"  # leading slash kept
    assert row["event_channel_logo_url"] == "/logo.png"
    assert json.loads(row["pregame_fallback"])["art_url"] == "/pre.png"
    # base + stored path resolves back to the original absolute URL
    assert (
        apply_art_base_url(row["program_art_url"], base)
        == "http://localhost:3000/{league}/cover.png"
    )


def test_divergent_origins_pick_most_frequent_winner():
    conn = _make_db()
    # a.com appears twice, b.com once -> a.com wins; b.com left absolute.
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, 'http://a.com/x.png')")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (2, 'http://a.com/y.png')")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (3, 'http://b.com/z.png')")

    _migrate_v75_extract_art_base_url(conn)

    assert (
        conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
        == "http://a.com"
    )

    # winner's URLs relativized (leading slash)
    def art(i):
        return conn.execute("SELECT program_art_url FROM templates WHERE id = ?", (i,)).fetchone()[
            0
        ]

    assert art(1) == "/x.png"
    assert art(2) == "/y.png"
    # loser's URL left absolute (resolver passes it through)
    assert (
        conn.execute("SELECT program_art_url FROM templates WHERE id = 3").fetchone()[0]
        == "http://b.com/z.png"
    )


def test_noop_when_already_configured():
    conn = _make_db()
    conn.execute("UPDATE settings SET art_base_url = 'http://preset.com' WHERE id = 1")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, 'http://other.com/x.png')")

    _migrate_v75_extract_art_base_url(conn)

    # User-set base preserved; URL untouched.
    assert (
        conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
        == "http://preset.com"
    )
    assert (
        conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
        == "http://other.com/x.png"
    )


def test_idempotent_second_run_noops():
    conn = _make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url) VALUES (1, 'http://localhost:3000/a.png')"
    )
    _migrate_v75_extract_art_base_url(conn)
    first = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    _migrate_v75_extract_art_base_url(conn)  # already configured -> no-op
    second = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    assert first == second == "/a.png"


@pytest.mark.parametrize(
    "value,base,expected",
    [
        ("/a.png", "http://x:3000", "http://x:3000/a.png"),
        ("a.png", "http://x:3000/", "http://x:3000/a.png"),
        ("https://espn.com/a.png", "http://x:3000", "https://espn.com/a.png"),
        ("", "http://x", ""),
        ("a.png", "", "a.png"),
    ],
)
def test_apply_art_base_url(value, base, expected):
    assert apply_art_base_url(value, base) == expected


# --- v76: leading-slash normalization -------------------------------------


def test_v76_adds_leading_slash_to_relative_paths():
    from teamarr.database.connection import _migrate_v76_leading_slash_art_paths

    conn = _make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url, pregame_fallback) "
        "VALUES (1, ?, ?, ?)",
        (
            "{league}/cover.png",  # relative, no slash
            "https://espn.com/logo.png",  # absolute — untouched
            json.dumps({"art_url": "pre.png"}),  # relative, no slash
        ),
    )

    _migrate_v76_leading_slash_art_paths(conn)

    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "/{league}/cover.png"
    assert row["event_channel_logo_url"] == "https://espn.com/logo.png"  # absolute kept
    assert json.loads(row["pregame_fallback"])["art_url"] == "/pre.png"


def test_v76_idempotent_on_already_slashed():
    from teamarr.database.connection import _migrate_v76_leading_slash_art_paths

    conn = _make_db()
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, '/already/ok.png')")
    _migrate_v76_leading_slash_art_paths(conn)
    val = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    assert val == "/already/ok.png"


# --- create/update normalization ------------------------------------------


def test_resolve_art_applies_base_uniformly(monkeypatch):
    """resolve_art (the single shared art entry point) prefixes the base for
    relative values, passes absolute through, and no-ops with no base — so every
    sink that uses it (EPG icon, Dispatcharr channel logo, fillers) reconstructs
    identically."""
    from teamarr.templates.resolver import TemplateResolver

    r = TemplateResolver("http://host:4999")
    # relative -> base prefixed
    monkeypatch.setattr(r, "resolve", lambda t, c: "/nba/cover.png")
    assert r.resolve_art("x", None) == "http://host:4999/nba/cover.png"
    # absolute -> passthrough (idempotent; another sink can't double-apply)
    monkeypatch.setattr(r, "resolve", lambda t, c: "http://other:9196/c.png")
    assert r.resolve_art("x", None) == "http://other:9196/c.png"
    # no base -> unchanged
    r2 = TemplateResolver("")
    monkeypatch.setattr(r2, "resolve", lambda t, c: "/nba/cover.png")
    assert r2.resolve_art("x", None) == "/nba/cover.png"


def test_create_update_normalize_art_paths():
    from teamarr.database.templates import _normalize_art_in_kwargs

    kw = {
        "program_art_url": "{league}/cover.png",
        "event_channel_logo_url": "https://espn.com/x.png",
        "pregame_fallback": {"art_url": "pre.png", "title": "t"},
        "name": "x",
    }
    _normalize_art_in_kwargs(kw)
    assert kw["program_art_url"] == "/{league}/cover.png"
    assert kw["event_channel_logo_url"] == "https://espn.com/x.png"  # absolute untouched
    assert kw["pregame_fallback"]["art_url"] == "/pre.png"
    assert kw["name"] == "x"  # non-art untouched
