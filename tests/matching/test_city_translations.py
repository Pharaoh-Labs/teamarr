"""City translations apply to provider team names too (#797).

CITY_TRANSLATIONS ran on stream text (normalize_for_matching) but not on
provider team names (normalize_text), so a native spelling ESPN itself uses
became a guaranteed miss: "1. FC Nürnberg" normalized to "1 fc nuremberg" on
the stream side and "1 fc nurnberg" on the team side, and residual_contradicts
read the disagreeing residual word as a different team — score 0. Found on a
Sky Deutschland EPG programme "2. BL | 1. FC Nürnberg - Hannover 96" while the
Darmstadt game on the next channel matched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teamarr.consumers.matching.normalizer import normalize_for_matching
from teamarr.consumers.matching.team_matcher import _best_name_score
from teamarr.core.types import Event, EventStatus, Team
from teamarr.utilities.constants import CITY_TRANSLATIONS
from teamarr.utilities.fuzzy_match import normalize_text, translate_cities

# Every ESPN soccer name whose native spelling contains a translated city,
# from a live /teams sweep on 2026-09-11. Each scored 0 against itself.
AFFECTED_ESPN_NAMES = [
    "1. FC Nürnberg",
    "Hannover 96",
    "TSV Eintracht Braunschweig",
    "Sevilla",
    "Venezia",
    "F.C. København",
    "IFK Göteborg",
]


def _team(team_id: str, name: str, league: str) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation="",
        league=league,
        sport="soccer",
    )


def _event(away: str, home: str, league: str) -> Event:
    start = datetime.now(UTC) + timedelta(hours=3)
    return Event(
        id="1",
        provider="espn",
        name=f"{away} at {home}",
        short_name=f"{away} at {home}",
        league=league,
        sport="soccer",
        start_time=start,
        home_team=_team("h", home, league),
        away_team=_team("a", away, league),
        status=EventStatus(state="scheduled"),
    )


class TestBothSidesTranslate:
    @pytest.mark.parametrize("name", AFFECTED_ESPN_NAMES)
    def test_normalizers_agree(self, name):
        assert normalize_for_matching(name) == normalize_text(name)

    @pytest.mark.parametrize("name", AFFECTED_ESPN_NAMES)
    def test_native_spelling_matches_its_own_team(self, name):
        stream = normalize_for_matching(name)
        assert _best_name_score(stream, _team("t", name, "ger.2")) == 100.0

    def test_translation_toward_the_provider_name_still_works(self):
        """The reason the table exists: ESPN writes "Bayern Munich"."""
        stream = normalize_for_matching("FC Bayern München")
        assert _best_name_score(stream, _team("t", "Bayern Munich", "ger.1")) == 100.0

    def test_translation_is_idempotent(self):
        """normalize_for_matching output is normalized again by normalize_text,
        so a second pass must not rewrite anything."""
        for english in CITY_TRANSLATIONS.values():
            assert translate_cities(english) == english
        for name in AFFECTED_ESPN_NAMES:
            once = normalize_for_matching(name)
            assert normalize_text(once) == once


class TestReportedProgramme:
    def test_nurnberg_hannover_matches(self, db_factory):
        from tests.fakes import make_team_matcher

        matcher = make_team_matcher(db_factory=db_factory)
        event = _event("Hannover 96", "1. FC Nürnberg", "ger.2")
        assert matcher._score_teams_against_event("1. FC Nürnberg", "Hannover 96", event)

    def test_builtin_alias_key_is_reachable(self, db_factory):
        """"sevilla fc" was keyed untranslated while lookups arrive translated."""
        from tests.fakes import make_team_matcher

        matcher = make_team_matcher(db_factory=db_factory)
        assert matcher._resolve_alias(normalize_for_matching("Sevilla FC"), "esp.1")
