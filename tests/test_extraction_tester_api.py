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


def test_month_day_without_date_toggle_warns():
    resp = _run(
        ExtractionPatterns(
            month_pattern=r"(?P<month>\d{2})", month_enabled=True,
            day_pattern=r"(?P<day>\d{2})", day_enabled=True,
        ),
        ["Game 07 16"],
    )
    assert resp.warnings
    # Pipeline gate: date extraction never attempted without date_enabled
    assert resp.results[0].date is None
