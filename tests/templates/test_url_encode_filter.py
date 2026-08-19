"""Tests for the `|urlencode` template filter (#478).

Motorsports and other variables whose values contain spaces or `&` truncated
art/poster URLs (e.g. game-thumbs) because the value was interpolated raw into
the query string. The opt-in `|urlencode` (alias `|url`) filter percent-encodes
the resolved value so it survives as a single query parameter.

Tests drive the substitution core directly via ``resolve_with_map`` so they
need no TemplateContext — the filter logic lives entirely in that path.
"""

from teamarr.templates.resolver import TemplateResolver


def _resolve(template: str, variables: dict[str, str]) -> str:
    return TemplateResolver().resolve_with_map(template, variables)


def test_urlencode_encodes_ampersand():
    # The bug: an '&' in the value split the query string at game-thumbs.
    out = _resolve(
        "/f1/cover?title={race_name|urlencode}&iconurl=",
        {"race_name": "Pit Stop & Podium"},
    )
    assert out == "/f1/cover?title=Pit%20Stop%20%26%20Podium&iconurl="


def test_urlencode_encodes_spaces():
    out = _resolve("{race_name|urlencode}", {"race_name": "Emilia Romagna Grand Prix"})
    assert out == "Emilia%20Romagna%20Grand%20Prix"


def test_url_alias_matches_urlencode():
    variables = {"race_name": "Grand Prix & Co"}
    assert _resolve("{race_name|url}", variables) == _resolve(
        "{race_name|urlencode}", variables
    )


def test_urlencode_leaves_literal_url_structure_untouched():
    # Only the substituted VALUE is encoded — the template's own '?', '&', '='
    # stay literal so the URL structure is preserved.
    out = _resolve(
        "/f1/cover?title={race_name|urlencode}&subtitle={session_name|urlencode}",
        {"race_name": "Monaco GP", "session_name": "Qualifying 1 & 2"},
    )
    assert out == "/f1/cover?title=Monaco%20GP&subtitle=Qualifying%201%20%26%202"


def test_unfiltered_variable_is_unchanged():
    # Without the filter, behavior is exactly as before (no encoding).
    out = _resolve("{race_name}", {"race_name": "Monaco & Grand Prix"})
    assert out == "Monaco & Grand Prix"


def test_urlencode_on_empty_value_yields_empty():
    out = _resolve("x={race_name|urlencode}", {"race_name": ""})
    assert out == "x="


def test_urlencode_encodes_slashes_and_reserved_chars():
    out = _resolve("{path|urlencode}", {"path": "a/b?c=d"})
    assert out == "a%2Fb%3Fc%3Dd"


def test_unknown_variable_with_filter_stays_literal():
    # A typo'd variable name keeps the whole token literal so the author sees it.
    out = _resolve("{nope|urlencode}", {"race_name": "x"})
    assert out == "{nope|urlencode}"


def test_unknown_filter_stays_literal():
    # A typo'd filter name keeps the whole token literal rather than silently
    # dropping the modifier.
    out = _resolve("{race_name|urlencodee}", {"race_name": "Monaco"})
    assert out == "{race_name|urlencodee}"


def test_urlencode_case_insensitive_filter_name():
    out = _resolve("{race_name|URLENCODE}", {"race_name": "A B"})
    assert out == "A%20B"
