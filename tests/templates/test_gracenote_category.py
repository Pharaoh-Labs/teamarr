"""{gracenote_category} — curated seeds + event_type-aware fallback (tvnk.12).

Reconciled against real captured Gracenote (docs/reference/gracenote-categories.md):
- team_vs_team leagues suffix the sport ('NFL Football', 'Premier League Soccer')
- event/event_card leagues title by series/promotion name alone
  ('NASCAR Craftsman Truck Series', not 'NASCAR Racing')
- international tournaments are branded without a sport suffix
  ('FIFA World Cup', composed with {year} in templates — real is 'FIFA World Cup 2026')
"""

import pytest

from teamarr.services.league_mappings import LeagueMappingService


@pytest.fixture
def service(db_factory):
    return LeagueMappingService(db_factory)


class TestCuratedSeeds:
    """Seed values must match real captured Gracenote titles."""

    @pytest.mark.parametrize(
        ("league", "expected"),
        [
            ("nfl", "NFL Football"),
            ("mlb", "MLB Baseball"),
            ("mens-college-basketball", "College Basketball"),
            # Club soccer keeps the ' Soccer' suffix (captured: real Gracenote)
            ("eng.1", "Premier League Soccer"),
            ("usa.1", "MLS Soccer"),
            # Racing series curated in the captured '<Brand> Racing' shape
            ("f1", "Formula 1 Racing"),
            ("indycar", "IndyCar Racing"),
            # Tennis is generic 'Tennis' (tournament name comes from event data)
            ("atp", "Tennis"),
            ("wta", "Tennis"),
        ],
    )
    def test_curated_value_wins(self, service, league, expected):
        assert service.get_gracenote_category(league) == expected

    @pytest.mark.parametrize(
        ("league", "expected"),
        [
            ("fifa.world", "FIFA World Cup"),
            ("fifa.wwc", "FIFA Women's World Cup"),
            ("uefa.euro", "UEFA Euro"),
            ("conmebol.america", "Copa America"),
            ("concacaf.gold", "CONCACAF Gold Cup"),
            ("concacaf.nations.league", "CONCACAF Nations League"),
        ],
    )
    def test_international_tournaments_have_no_sport_suffix(
        self, service, league, expected
    ):
        """Real Gracenote is branded + year ('FIFA World Cup 2026'), never
        'FIFA World Cup Soccer'. The year is template-composed, not seeded."""
        assert service.get_gracenote_category(league) == expected


class TestEventTypeAwareFallback:
    """Uncurated leagues auto-generate by event_type shape."""

    @pytest.mark.parametrize(
        ("league", "expected"),
        [
            # Racing: series name alone (captured: 'NASCAR Craftsman Truck Series').
            # These were curated 'NASCAR Racing'/'Motor Racing' — regressions vs
            # their own display_name — and are now served by the fallback.
            ("nascar-cup", "NASCAR Cup Series"),
            ("nascar-truck", "NASCAR Craftsman Truck Series"),
            ("nascar-xfinity", "NASCAR O'Reilly Auto Parts Series"),
            ("imsa", "IMSA WeatherTech SportsCar Championship"),
            ("wec", "FIA World Endurance Championship"),
        ],
    )
    def test_event_leagues_use_display_name_alone(self, service, league, expected):
        assert service.get_gracenote_category(league) == expected

    def test_event_card_uses_promotion_name_alone(self, service):
        result = service.get_gracenote_category("ufc")
        assert result == "Ultimate Fighting Championship"
        assert not result.endswith("MMA")

    def test_event_card_does_not_double_the_sport(self, service):
        # Old fallback produced 'Boxing Boxing' (display_name + sport)
        assert service.get_gracenote_category("boxing") == "Boxing"

    def test_team_vs_team_fallback_still_appends_sport(self, service):
        # Uncurated head-to-head league keeps the '{display_name} {Sport}' shape
        assert service.get_gracenote_category("ohl") == "Ontario Hockey League Hockey"

    def test_unknown_league_falls_back_to_uppercased_code(self, service):
        # No event_type and no sport known → display-name fallback chain ends
        # at league_code.upper() (pre-existing get_league_display_name behavior)
        assert service.get_gracenote_category("no-such-league") == "NO-SUCH-LEAGUE"
