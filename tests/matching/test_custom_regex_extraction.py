"""Custom-regex extraction semantics (#456, bead 0tgt.2).

Named groups must take precedence over numbered groups in the teams and
fighters extractors: named groups are also numbered, so a pattern mixing
(?P<team1>...) with an extra unnamed group — a hand-written (vs|v)
separator or an (ESPN|FOX): prefix — used to return the wrong captures
with success=True. The Pattern Tester highlights named groups, so the
old behavior looked correct in the tester and mismatched in the pipeline.

Also pins the date formats the custom date extractor must parse: the
tester only shows that the regex MATCHED, so every shape a user would
reasonably capture has to make it through _parse_date_string.
"""

from datetime import date, datetime

from teamarr.consumers.matching.classifier import (
    CustomRegexConfig,
    extract_date_with_custom_regex,
    extract_fighters_with_custom_regex,
    extract_teams_with_custom_regex,
)


def _teams_cfg(pattern: str) -> CustomRegexConfig:
    return CustomRegexConfig(teams_pattern=pattern, teams_enabled=True)


def _fighters_cfg(pattern: str) -> CustomRegexConfig:
    return CustomRegexConfig(fighters_pattern=pattern, fighters_enabled=True)


class TestNamedGroupPrecedence:
    def test_unnamed_separator_group_does_not_shadow_named_teams(self):
        # The (vs|v) alternation is numbered group 2 — the old numbered-first
        # order returned ('Lakers', 'vs') here.
        cfg = _teams_cfg(r"(?P<team1>[\w ]+?) (vs|v) (?P<team2>[\w ]+)")
        assert extract_teams_with_custom_regex("Lakers vs Celtics", cfg) == (
            "Lakers",
            "Celtics",
            True,
        )

    def test_unnamed_prefix_group_does_not_shadow_named_teams(self):
        cfg = _teams_cfg(r"(ESPN|FOX): (?P<team1>[\w ]+?) vs (?P<team2>[\w ]+)")
        assert extract_teams_with_custom_regex("ESPN: Yankees vs Red Sox", cfg) == (
            "Yankees",
            "Red Sox",
            True,
        )

    def test_fighters_follow_the_same_precedence(self):
        cfg = _fighters_cfg(r"(?P<fighter1>[\w ]+?) (vs|v) (?P<fighter2>[\w ]+)")
        assert extract_fighters_with_custom_regex("Jones vs Miocic", cfg) == (
            "Jones",
            "Miocic",
            True,
        )

    def test_unnamed_only_pattern_uses_first_two_groups(self):
        cfg = _teams_cfg(r"([\w ]+?) vs ([\w ]+)")
        assert extract_teams_with_custom_regex("Lakers vs Celtics", cfg) == (
            "Lakers",
            "Celtics",
            True,
        )

    def test_other_group_names_fall_back_to_numbered(self):
        # Neither team1 nor team2 declared → numbered path, which is correct
        # for a clean two-group pattern regardless of what it names them.
        cfg = _teams_cfg(r"(?P<away>[\w ]+?) at (?P<home>[\w ]+)")
        assert extract_teams_with_custom_regex("Yankees at Red Sox", cfg) == (
            "Yankees",
            "Red Sox",
            True,
        )

    def test_declared_named_group_that_captures_empty_fails_closed(self):
        # team2 is optional and absent — the named path must fail rather than
        # fall back to numbered groups (which would resurrect the garbage the
        # precedence exists to avoid).
        cfg = _teams_cfg(r"(?P<team1>[\w ]+?) vs ?(?P<team2>[\w ]*)")
        assert extract_teams_with_custom_regex("Lakers vs", cfg) == (None, None, False)

    def test_no_match_returns_false(self):
        cfg = _teams_cfg(r"(?P<team1>\w+) vs (?P<team2>\w+)")
        assert extract_teams_with_custom_regex("Grand Prix Qualifying", cfg) == (
            None,
            None,
            False,
        )


class TestCustomDateFormats:
    def _extract(self, pattern: str, text: str):
        cfg = CustomRegexConfig(date_pattern=pattern, date_enabled=True)
        extracted, _trusted = extract_date_with_custom_regex(text, cfg)
        return extracted

    def test_yearless_numeric_slash_date_parses(self):
        # Matched fine in the JS tester, silently extracted nothing before #456.
        got = self._extract(r"(?P<date>\d{1,2}/\d{1,2})(?!\d)", "MLB 7/15 Tigers vs Royals")
        assert got == date(datetime.now().year, 7, 15)

    def test_yearless_day_first_slash_date_parses(self):
        # 15/7 can't be month-first, so the %d/%m fallback picks it up.
        got = self._extract(r"(?P<date>\d{1,2}/\d{1,2})(?!\d)", "EPL 15/7 Fulham vs Burnley")
        assert got == date(datetime.now().year, 7, 15)

    def test_yearless_numeric_dash_date_parses(self):
        got = self._extract(r"(?P<date>\d{1,2}-\d{1,2})(?!\d)", "NBA 7-15 Lakers vs Celtics")
        assert got == date(datetime.now().year, 7, 15)

    def test_word_month_with_year_parses(self):
        got = self._extract(r"(?P<date>[A-Za-z]+ \d{1,2},? \d{4})", "UFC Jan 14 2026 Card")
        assert got == date(2026, 1, 14)

    def test_word_month_with_comma_year_parses(self):
        got = self._extract(
            r"(?P<date>[A-Za-z]+ \d{1,2},? \d{4})", "Boxing January 14, 2026 PPV"
        )
        assert got == date(2026, 1, 14)

    def test_dotted_european_date_parses(self):
        got = self._extract(r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4})", "DEL 15.07.2026 Spiel")
        assert got == date(2026, 7, 15)
