#!/usr/bin/env python3
"""
Real Events Test - Tests matching against ACTUAL ESPN events for today.

This is the honest test: can we match streams to real scheduled events?

Run: python experiments/real_events_test.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from teamarr.consumers import MultiLeagueMatcher
from teamarr.services import create_default_service

# Test streams - mix of real patterns
TEST_STREAMS = [
    # NHL - should have games today
    "ESPN+ 20 : Montreal Canadiens vs. Florida Panthers @ Dec 30 04:00 PM ET",
    "ESPN+ 21 : New Jersey Devils vs. Carolina Hurricanes @ Dec 30 05:00 PM ET",
    "ESPN+ 22 : Columbus Blue Jackets vs. Washington Capitals @ Dec 30 05:00 PM ET",
    "ESPN+ 23 : Buffalo Sabres vs. Pittsburgh Penguins @ Dec 30 05:00 PM ET",
    "ESPN+ 24 : Philadelphia Flyers vs. New York Rangers @ Dec 30 05:00 PM ET",
    "ESPN+ 25 : Winnipeg Jets vs. Minnesota Wild @ Dec 30 05:00 PM ET",
    "ESPN+ 31 : Chicago Blackhawks vs. Edmonton Oilers @ Dec 30 08:00 PM ET",

    # NBA - should have games today
    "ESPN+ 143 : Oklahoma City Thunder vs. Boston Celtics @ Dec 30 07:30 PM ET",
    "ESPN+ 144 : Milwaukee Bucks vs. Chicago Bulls @ Dec 30 08:00 PM ET",
    "ESPN+ 148 : Miami Heat vs. Orlando Magic @ Dec 30 07:00 PM ET",
    "ESPN+ 149 : Cleveland Cavaliers vs. Detroit Pistons @ Dec 30 07:00 PM ET",

    # EPL - check if there are games
    "ESPN+ 68 : Arsenal vs. Manchester City @ Dec 30 12:30 PM ET",
    "ESPN+ 69 : Liverpool vs. Manchester United @ Dec 30 03:00 PM ET",

    # Bundesliga
    "ESPN+ 77 : Bayern Munich vs. Borussia Dortmund @ Dec 30 12:30 PM ET",
    "ESPN+ 81 : Hertha BSC vs. Hamburger SV @ Dec 30 12:30 PM ET",

    # MLS (likely off-season)
    "ESPN+ 61 : Austin FC vs. Houston Dynamo @ Dec 30 08:00 PM ET",

    # College Basketball - likely active
    "ESPN+ 05 : Vermont vs. Princeton @ Dec 30 03:00 PM ET",
    "ESPN+ 36 : Seton Hall vs. Georgetown @ Dec 30 05:00 PM ET",

    # College Football Bowl Games
    "ESPN+ 55 : Oregon vs. Ohio State (Fiesta Bowl) @ Dec 30 08:00 PM ET",
    "ESPN+ 57 : Texas vs. Arizona State (Peach Bowl) @ Dec 30 01:00 PM ET",

    # Talk shows (should NOT match)
    "ESPN+ 01 : Clinton & Friends @ Dec 30 10:00 AM ET",
    "ESPN+ 02 : The Pat McAfee Show @ Dec 30 12:00 PM ET",

    # Spanish variants
    "ESPN+ 33 : En Español - Montreal Canadiens vs. Florida Panthers @ Dec 30 04:00 PM ET",
    "ESPN+ 75 : En Español - Arsenal vs. Manchester City @ Dec 30 12:30 PM ET",
]

# Leagues to search - comprehensive list from our system
SEARCH_LEAGUES = [
    # Major US Pro
    "nhl", "nba", "nfl", "mlb", "mls", "wnba",
    # College
    "mens-college-basketball", "womens-college-basketball", "college-football",
    # Soccer - ESPN
    "eng.1", "eng.2", "ger.1", "ger.2", "esp.1", "fra.1", "ita.1",
    "uefa.champions", "uefa.europa",
    # TheSportsDB leagues
    "ohl", "whl", "qmjhl", "nll",
]


def main():
    print("=" * 80)
    print("  REAL EVENTS TEST - Matching Against Today's Events (All Providers)")
    print("=" * 80)
    print(f"\n  Target date: {date.today()}")
    print(f"  Leagues to search: {SEARCH_LEAGUES}")
    print()

    # Initialize service with ALL providers (ESPN + TheSportsDB)
    service = create_default_service()

    matcher = MultiLeagueMatcher(
        service,
        search_leagues=SEARCH_LEAGUES,
        include_leagues=SEARCH_LEAGUES,  # Include all for testing
    )

    # Run matching
    print("Fetching events from ESPN and matching streams...")
    result = matcher.match_all(TEST_STREAMS, date.today())

    # Results
    print("\n" + "=" * 80)
    print("  RESULTS")
    print("=" * 80)

    print(f"\n  Events found across all leagues: {result.events_found}")
    print(f"  Streams tested: {result.total}")
    print(f"  Matched: {result.matched_count}")
    print(f"  Included (in whitelist): {result.included_count}")
    print(f"  Unmatched: {result.unmatched_count}")
    print(f"  Match rate: {result.match_rate:.1%}")

    # Show matched streams
    print("\n" + "-" * 80)
    print("  MATCHED STREAMS (found real events)")
    print("-" * 80)

    for r in result.results:
        if r.matched:
            print(f"\n  ✓ {r.stream_name}")
            print(f"    → {r.event.name} [{r.league}]")
            print(f"    → {r.event.start_time.strftime('%Y-%m-%d %I:%M %p')}")

    # Show unmatched streams
    print("\n" + "-" * 80)
    print("  UNMATCHED STREAMS (no events found)")
    print("-" * 80)

    for r in result.results:
        if not r.matched:
            reason = r.exclusion_reason or "unknown"
            print(f"\n  ✗ {r.stream_name}")
            print(f"    Reason: {reason}")

    # Summary by league
    print("\n" + "-" * 80)
    print("  EVENTS BY LEAGUE")
    print("-" * 80)

    league_counts = {}
    for r in result.results:
        if r.matched:
            league = r.league
            if league not in league_counts:
                league_counts[league] = 0
            league_counts[league] += 1

    for league, count in sorted(league_counts.items()):
        print(f"  {league}: {count} matched")

    print("\n" + "=" * 80)
    print("  HONEST ASSESSMENT")
    print("=" * 80)
    print(f"""
  This test uses REAL ESPN API data for {date.today()}.

  Match rate of {result.match_rate:.1%} reflects:
  - Which teams actually have games scheduled today
  - Whether our stream names align with real events
  - API availability and data quality

  Unmatched streams could be:
  - Fake/synthetic matchups (teams not playing today)
  - Talk shows, documentaries (correctly unmatched)
  - Leagues not in our search list
  - Off-season sports (MLS in December)
    """)


if __name__ == "__main__":
    main()
