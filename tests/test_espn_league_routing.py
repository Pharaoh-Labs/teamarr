"""Regression tests for ESPN provider league routing (#218, teamarrv2-4vz).

ESPN.supports_league() decides whether ESPN claims a league during the
provider race in SportsDataService (ESPN is priority 0, so it wins ties).

Bug #218: a league explicitly configured in the leagues table for a DIFFERENT
provider (uru.2 -> tsdb, because ESPN's uru.2 data is stale from 2010-2011)
was still claimed by ESPN, because the dotted-soccer dynamic-discovery
heuristic ("." in league -> True) ran BEFORE honoring the DB assignment.
Discovered soccer leagues (not in the leagues table) must still resolve via
that heuristic.
"""

from teamarr.providers.espn.provider import ESPNProvider


class FakeMappingSource:
    """Minimal stand-in for LeagueMappingService.

    Backed by a {(league_code, provider)} set, mirroring the real service's
    in-memory index built from the leagues table.
    """

    def __init__(self, mappings: set[tuple[str, str]]):
        self._mappings = {(code.lower(), prov) for code, prov in mappings}

    def supports_league(self, league_code: str, provider: str) -> bool:
        return (league_code.lower(), provider) in self._mappings

    def get_mapping_by_league(self, league_code: str):
        code = league_code.lower()
        for mapped_code, _provider in self._mappings:
            if mapped_code == code:
                return object()  # non-None == "configured for some provider"
        return None


def _espn(mappings: set[tuple[str, str]]) -> ESPNProvider:
    return ESPNProvider(league_mapping_source=FakeMappingSource(mappings))


class TestESPNSupportsLeague:
    def test_declines_league_assigned_to_other_provider(self):
        """#218: uru.2 is tsdb-only; ESPN must decline despite the dot."""
        espn = _espn({("uru.2", "tsdb")})
        assert espn.supports_league("uru.2") is False

    def test_claims_espn_mapped_dotted_league(self):
        """Soccer leagues explicitly mapped to ESPN are still claimed."""
        espn = _espn({("eng.1", "espn"), ("usa.1", "espn")})
        assert espn.supports_league("eng.1") is True
        assert espn.supports_league("usa.1") is True

    def test_claims_discovered_dotted_league_not_in_table(self):
        """Dynamic discovery: a dotted league not in the table still resolves."""
        espn = _espn(set())
        assert espn.supports_league("fra.99") is True

    def test_claims_espn_mapped_nondotted_league(self):
        espn = _espn({("nba", "espn")})
        assert espn.supports_league("nba") is True

    def test_declines_nondotted_league_assigned_to_other_provider(self):
        """The guard also covers non-dotted leagues owned by another provider."""
        espn = _espn({("chl", "hockeytech")})
        assert espn.supports_league("chl") is False

    def test_no_mapping_source_falls_back_to_dot_heuristic(self):
        """Without a mapping source, only the dotted heuristic applies."""
        espn = ESPNProvider(league_mapping_source=None)
        assert espn.supports_league("fra.99") is True
        assert espn.supports_league("nba") is False


class _SportSource:
    """Mapping source stub exercising _get_sport's resolution chain.

    Returns no display mapping; ``get_league_sport`` is the cached-sport lookup.
    """

    def __init__(self, cached: dict[str, str] | None = None):
        self._cached = cached or {}

    def get_mapping(self, league, provider):
        return None

    def get_league_sport(self, league):
        return self._cached.get(league)


class TestGetSport:
    """_get_sport: discovered ESPN soccer slugs must resolve to 'soccer', not 'unknown'."""

    def test_dotted_discovered_league_infers_soccer(self):
        # bug: bra.carioca.groupa / ger.a.bayernliganorth / afc.challenge_cup
        # were cached as sport='unknown' (shown as "Unknown" in the selector).
        espn = ESPNProvider(league_mapping_source=_SportSource())
        assert espn._get_sport("bra.carioca.groupa") == "soccer"
        assert espn._get_sport("ger.a.bayernliganorth") == "soccer"
        assert espn._get_sport("afc.challenge_cup") == "soccer"

    def test_dotted_inference_works_without_mapping_source(self):
        espn = ESPNProvider(league_mapping_source=None)
        assert espn._get_sport("eng.1") == "soccer"

    def test_nondotted_unknown_stays_unknown(self):
        espn = ESPNProvider(league_mapping_source=_SportSource())
        assert espn._get_sport("mysteryleague") == "unknown"

    def test_cached_sport_takes_precedence_over_dot_inference(self):
        # A dotted league explicitly cached as another sport is not overridden.
        espn = ESPNProvider(league_mapping_source=_SportSource({"foo.bar": "cricket"}))
        assert espn._get_sport("foo.bar") == "cricket"
