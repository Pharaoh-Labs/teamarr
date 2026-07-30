"""Pattern Tester pipeline-truth endpoint tests (#458).

The endpoint must mirror the real extraction pipeline exactly — including
the two-required-groups rule (#456) and date parseability — so the tester
stops green-lighting patterns the pipeline would reject.
"""

from teamarr.api.routes.groups import (
    ExtractionPatterns,
    TestExtractionRequest,
)
from teamarr.api.routes.groups import (
    test_extraction as run_extraction,  # aliased so pytest doesn't collect it
)


def _run(patterns: ExtractionPatterns, names: list[str]):
    return run_extraction(TestExtractionRequest(stream_names=names, patterns=patterns))


def test_teams_named_groups_with_extra_unnamed_group():
    # (ESPN|FOX) prefix group would corrupt numbered captures — named groups win (#456)
    resp = _run(
        ExtractionPatterns(
            teams_pattern=r"(ESPN|FOX): (?P<team1>.+?) vs (?P<team2>.+)",
            teams_enabled=True,
        ),
        ["ESPN: Tigers vs Twins", "TNT: Lakers vs Bulls"],
    )
    assert resp.results[0].teams.matched is True
    assert resp.results[0].teams.values == ["Tigers", "Twins"]
    assert resp.results[1].teams.matched is False
    assert resp.results[1].teams.values == []


def test_teams_single_group_fails_pipeline():
    # JS regex would highlight this as a match; pipeline requires BOTH teams
    resp = _run(
        ExtractionPatterns(teams_pattern=r"(?P<team1>\w+) game", teams_enabled=True),
        ["Tigers game"],
    )
    assert resp.results[0].teams.matched is False


def test_date_unparseable_fails():
    resp = _run(
        ExtractionPatterns(date_pattern=r"(?P<date>\d{2}\.\d{2}\.\d{4}\.\d+)", date_enabled=True),
        ["Game 16.07.2026.999"],
    )
    assert resp.results[0].date.matched is False


def test_date_parseable_returns_iso():
    resp = _run(
        ExtractionPatterns(date_pattern=r"(?P<date>\d{2}/\d{2}/\d{4})", date_enabled=True),
        ["Tigers vs Twins 07/16/2026"],
    )
    assert resp.results[0].date.matched is True
    assert resp.results[0].date.values == ["2026-07-16"]


def test_disabled_fields_are_null():
    resp = _run(
        ExtractionPatterns(teams_pattern=r"(.+) vs (.+)", teams_enabled=True),
        ["A vs B"],
    )
    r = resp.results[0]
    assert r.teams is not None
    assert r.date is None
    assert r.time is None
    assert r.league is None
    assert r.fighters is None
    assert r.event_name is None


def test_invalid_regex_reported():
    resp = _run(
        ExtractionPatterns(teams_pattern=r"(unclosed", teams_enabled=True),
        ["A vs B"],
    )
    assert "teams" in resp.pattern_errors
    assert resp.results[0].teams.matched is False


def test_month_day_only_extracts(month_first=True):
    # #485: month/day-only configs were silently dead behind the date toggle
    resp = _run(
        ExtractionPatterns(
            month_pattern=r"m(?P<month>\d{2})", month_enabled=True,
            day_pattern=r"d(?P<day>\d{2})", day_enabled=True,
        ),
        ["Game m07 d16"],
    )
    assert not resp.warnings
    assert resp.results[0].date is not None
    assert resp.results[0].date.matched is True
    assert resp.results[0].date.values[0].endswith("-07-16")


# --- JS/.NET-style named groups accepted (#494) ---
# The edit form displays patterns in JS syntax ((?<team1>), so users see and
# write that form. Both the tester and the pipeline translate it to Python
# syntax before compiling.


def test_js_style_named_groups_accepted():
    resp = _run(
        ExtractionPatterns(
            teams_pattern=r"(?<team1>.+?) vs (?<team2>.+)",
            teams_enabled=True,
        ),
        ["Tigers vs Twins"],
    )
    assert resp.pattern_errors == {}
    assert resp.results[0].teams.matched is True
    assert resp.results[0].teams.values == ["Tigers", "Twins"]


def test_js_style_date_pattern_accepted():
    resp = _run(
        ExtractionPatterns(date_pattern=r"(?<date>\d{2}/\d{2}/\d{4})", date_enabled=True),
        ["Tigers vs Twins 07/16/2026"],
    )
    assert resp.pattern_errors == {}
    assert resp.results[0].date.matched is True
    assert resp.results[0].date.values == ["2026-07-16"]


def test_lookbehind_not_mangled_by_syntax_translation():
    # (?<=...) and (?<!...) must survive the (?<name> -> (?P<name> translation
    resp = _run(
        ExtractionPatterns(
            teams_pattern=r"(?<=: )(?P<team1>\w+) vs (?P<team2>\w+)(?<! HD)",
            teams_enabled=True,
        ),
        ["MLB: Tigers vs Twins"],
    )
    assert resp.pattern_errors == {}
    assert resp.results[0].teams.matched is True
