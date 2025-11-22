#!/usr/bin/env python3
"""
Variable Audit Tool - Uses REAL ESPN API data for actual audit
"""

import sys
sys.path.insert(0, '/srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr/teamarr-redux')

from api.espn_client import ESPNClient
from epg.template_engine import TemplateEngine
from epg.orchestrator import EPGOrchestrator
from datetime import datetime, timedelta
import json

def fetch_real_context():
    """Fetch real ESPN API data for Boston Celtics"""

    print("Fetching REAL data from ESPN API...")
    print("Team: Boston Celtics (NBA)")
    print()

    client = ESPNClient()
    orchestrator = EPGOrchestrator()  # For normalization helper

    # Celtics team ID
    team_id = '2'  # Boston Celtics
    league = 'nba'
    sport = 'basketball'

    team_config = {
        'espn_team_id': team_id,
        'team_name': 'Boston Celtics',
        'team_abbrev': 'BOS',
        'sport': sport,
        'league': league,
        'league_name': 'NBA'
    }

    print("1. Fetching schedule...")
    schedule = client.get_team_schedule(sport, league, team_id, days_ahead=60)

    if not schedule or 'events' not in schedule:
        print("ERROR: Could not fetch schedule")
        return None

    events = schedule.get('events', [])
    print(f"   Found {len(events)} events")

    # Find current, next, and last games
    from datetime import timezone
    now = datetime.now(timezone.utc)

    past_events = [e for e in events if datetime.fromisoformat(e['date'].replace('Z', '+00:00')) < now]
    future_events = [e for e in events if datetime.fromisoformat(e['date'].replace('Z', '+00:00')) >= now]

    past_events.sort(key=lambda x: x['date'], reverse=True)  # Most recent first
    future_events.sort(key=lambda x: x['date'])  # Soonest first

    last_game = past_events[0] if past_events else None
    current_game = future_events[0] if future_events else None
    next_game = future_events[1] if len(future_events) > 1 else None

    print(f"\n2. Game selection:")
    if last_game:
        print(f"   LAST: {last_game.get('name', 'Unknown')} - {last_game.get('date')}")
    if current_game:
        print(f"   CURRENT: {current_game.get('name', 'Unknown')} - {current_game.get('date')}")
    if next_game:
        print(f"   NEXT: {next_game.get('name', 'Unknown')} - {next_game.get('date')}")

    print("\n3. Fetching team stats...")
    team_stats = client.get_team_stats(sport, league, team_id)
    if team_stats:
        print(f"   Team stats fetched: {list(team_stats.keys())}")

    print("\n4. Fetching scoreboard (for completed games)...")
    # Get scoreboard to enrich past games with final scores/attendance
    scoreboard = client.get_scoreboard(sport, league)

    # Normalize events (ESPN API structure -> template engine structure)
    print("\n5. Normalizing ESPN API structure...")
    if current_game:
        current_game = orchestrator._normalize_event(current_game)
    if next_game:
        next_game = orchestrator._normalize_event(next_game)
    if last_game:
        last_game = orchestrator._normalize_event(last_game)

    # Calculate streaks from schedule data
    print("\n6. Calculating streaks...")
    streaks = orchestrator._calculate_home_away_streaks(team_id, schedule)
    print(f"   Calculated streaks: {streaks}")

    # Fetch opponent stats for current game
    print("\n7. Fetching opponent stats...")
    current_opponent_stats = {}
    if current_game:
        current_opponent_id = current_game.get('away_team', {}).get('id')
        if current_opponent_id:
            current_opponent_stats = client.get_team_stats(sport, league, current_opponent_id) or {}
            print(f"   Current opponent ({current_opponent_id}): {current_opponent_stats.get('record', {}).get('summary', 'N/A')}")

    # Fetch player leaders for current game
    print("\n8. Fetching player leaders...")
    current_player_leaders = {}
    if current_game and current_game.get('competitions'):
        current_player_leaders = orchestrator._extract_player_leaders(
            current_game['competitions'][0],
            team_id,
            sport,
            league
        )
        print(f"   Current game leader: {current_player_leaders.get('basketball_top_scorer_name', 'None')}")

    # Build context
    context = {
        'team_config': team_config,
        'team_stats': team_stats or {},
        'opponent_stats': current_opponent_stats,
        'h2h': {},
        'streaks': streaks,
        'head_coach': '',
        'player_leaders': current_player_leaders,
        'epg_timezone': 'America/New_York',
        'game': current_game,
    }

    # Add next game context
    if next_game:
        next_opponent_stats = {}
        next_opponent_id = next_game.get('away_team', {}).get('id')
        if next_opponent_id:
            next_opponent_stats = client.get_team_stats(sport, league, next_opponent_id) or {}
            print(f"   Next opponent ({next_opponent_id}): {next_opponent_stats.get('record', {}).get('summary', 'N/A')}")

        next_player_leaders = {}
        if next_game.get('competitions'):
            next_player_leaders = orchestrator._extract_player_leaders(
                next_game['competitions'][0],
                team_id,
                sport,
                league
            )
            print(f"   Next game leader: {next_player_leaders.get('basketball_top_scorer_name', 'None')}")

        context['next_game'] = {
            'game': next_game,
            'opponent_stats': next_opponent_stats,
            'h2h': {},
            'streaks': {},
            'head_coach': '',
            'player_leaders': next_player_leaders
        }

    # Add last game context
    if last_game:
        last_opponent_stats = {}
        last_opponent_id = last_game.get('away_team', {}).get('id')
        if last_opponent_id:
            last_opponent_stats = client.get_team_stats(sport, league, last_opponent_id) or {}
            print(f"   Last opponent ({last_opponent_id}): {last_opponent_stats.get('record', {}).get('summary', 'N/A')}")

        last_player_leaders = {}
        if last_game.get('competitions'):
            last_player_leaders = orchestrator._extract_player_leaders(
                last_game['competitions'][0],
                team_id,
                sport,
                league
            )
            print(f"   Last game leader: {last_player_leaders.get('basketball_top_scorer_name', 'None')}")

        context['last_game'] = {
            'game': last_game,
            'opponent_stats': last_opponent_stats,
            'h2h': {},
            'streaks': {},
            'head_coach': '',
            'player_leaders': last_player_leaders
        }

    print("\n9. Context built successfully!")
    return context

def show_variable(var_name, variables, var_number, total_vars):
    """Display a single variable with all three contexts"""

    base = variables.get(var_name, '')
    next_val = variables.get(f"{var_name}.next", '')
    last_val = variables.get(f"{var_name}.last", '')

    print(f"\n{'='*80}")
    print(f"VARIABLE {var_number}/{total_vars}: {var_name}")
    print(f"{'='*80}")
    print(f"BASE  (current): '{base}'")
    print(f".next (next game): '{next_val}'")
    print(f".last (last game): '{last_val}'")
    print()

    # Analysis
    same_as_base = (base == next_val == last_val)
    base_next_same = (base == next_val and base != '')
    base_last_same = (base == last_val and base != '')

    all_empty = (base == '' and next_val == '' and last_val == '')

    if all_empty:
        print("⚠️  ANALYSIS: All three values are EMPTY")
        print("   → No data available in API response")
        print("   → RECOMMENDATION: Need to check with populated game data")
    elif same_as_base and base != '':
        print("⚠️  ANALYSIS: All three values are IDENTICAL")
        print("   → This variable does NOT vary by game context")
        print("   → RECOMMENDATION: Remove .next and .last suffixes")
    elif base_next_same and base_last_same:
        print("⚠️  ANALYSIS: All values match when populated")
        print("   → RECOMMENDATION: Remove .next and .last suffixes")
    elif base != next_val or base != last_val or next_val != last_val:
        print("✓  ANALYSIS: Values DIFFER across contexts")
        print("   → This variable IS game-specific")
        print("   → RECOMMENDATION: Keep .next and .last suffixes")
    else:
        print("?  ANALYSIS: Unable to determine")

    print()

if __name__ == '__main__':
    # Fetch real data
    context = fetch_real_context()

    if not context:
        print("Failed to fetch data from ESPN API")
        sys.exit(1)

    print("\nGenerating variables from REAL ESPN data...")
    engine = TemplateEngine()
    variables = engine._build_variable_dict(context)

    # Get all unique base variable names (without suffixes)
    base_vars = sorted([k for k in variables.keys() if '.' not in k])

    print(f"\nTotal base variables: {len(base_vars)}")
    print(f"Total with suffixes: {len(variables)}")
    print("\nStarting variable-by-variable audit with REAL DATA...\n")

    # Show specific variable
    var_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    if var_num > 0 and var_num <= len(base_vars):
        show_variable(base_vars[var_num - 1], variables, var_num, len(base_vars))
    else:
        print(f"Usage: python3 variable_audit_live.py <number 1-{len(base_vars)}>")
        print(f"\nFirst 10 variables:")
        for i, var in enumerate(base_vars[:10], 1):
            print(f"  {i}. {var}")
