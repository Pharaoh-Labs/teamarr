#!/usr/bin/env python3
"""
Variable Audit Tool - Shows actual data for each variable across all 3 contexts
"""

import sys
sys.path.insert(0, '/srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr/teamarr-redux')

from epg.template_engine import TemplateEngine
from datetime import datetime

def create_full_context():
    """Create a comprehensive context with all possible data populated"""

    team_config = {
        'espn_team_id': '1',
        'team_name': 'Boston Celtics',
        'team_abbrev': 'BOS',
        'sport': 'basketball',
        'league': 'nba',
        'league_name': 'NBA'
    }

    team_stats = {
        'record': {'wins': 20, 'losses': 5, 'ties': 0, 'winPercent': 0.800},
        'rank': 3,
        'ppg': 115.5,
        'papg': 108.2,
        'streak_count': 3,  # 3-game win streak
        'home_record': '12-2',
        'away_record': '8-3',
        'division_record': '7-1',
        'playoff_seed': 2,
        'games_back': 0.5,
        'conference_full_name': 'Eastern Conference',
        'conference_abbrev': 'EC',
        'division_name': 'Atlantic Division'
    }

    # CURRENT GAME: Celtics vs Lakers (home game)
    current_game = {
        'home_team': {
            'id': '1',
            'name': 'Boston Celtics',
            'abbrev': 'BOS',
            'score': 0
        },
        'away_team': {
            'id': '13',
            'name': 'Los Angeles Lakers',
            'abbrev': 'LAL',
            'score': 0,
            'record': {'wins': 18, 'losses': 7}
        },
        'date': '2025-01-15T19:00:00Z',
        'venue': {
            'name': 'TD Garden',
            'city': 'Boston',
            'state': 'MA'
        },
        'status': {
            'name': 'Scheduled',
            'detail': '',
            'period': 0
        },
        'season': {'type': 2, 'year': '2025'},
        'competitions': [{
            'broadcasts': [
                {
                    'type': {'shortName': 'TV'},
                    'market': {'type': 'National'},
                    'media': {'shortName': 'ESPN'}
                }
            ],
            'odds': [{
                'provider': {'name': 'ESPN BET'},
                'spread': 2.5,
                'overUnder': 225.5,
                'details': 'BOS -2.5',
                'homeTeamOdds': {'favorite': True, 'moneyLine': -150, 'spreadOdds': -110},
                'awayTeamOdds': {'underdog': True, 'moneyLine': +130, 'spreadOdds': -110}
            }],
            'attendance': 0
        }]
    }

    current_opponent_stats = {
        'record': {'wins': 18, 'losses': 7, 'winPercent': 0.720},
        'rank': 5,
        'ppg': 112.3,
        'papg': 109.8
    }

    # NEXT GAME: Celtics @ Clippers (away game)
    next_game = {
        'home_team': {
            'id': '12',
            'name': 'Los Angeles Clippers',
            'abbrev': 'LAC',
            'score': 0
        },
        'away_team': {
            'id': '1',
            'name': 'Boston Celtics',
            'abbrev': 'BOS',
            'score': 0
        },
        'date': '2025-01-17T22:30:00Z',
        'venue': {
            'name': 'Crypto.com Arena',
            'city': 'Los Angeles',
            'state': 'CA'
        },
        'status': {'name': 'Scheduled'},
        'season': {'type': 2, 'year': '2025'},
        'competitions': [{
            'broadcasts': [
                {
                    'type': {'shortName': 'TV'},
                    'market': {'type': 'National'},
                    'media': {'shortName': 'TNT'}
                }
            ]
        }]
    }

    next_opponent_stats = {
        'record': {'wins': 19, 'losses': 6, 'winPercent': 0.760},
        'rank': 4,
        'ppg': 116.8,
        'papg': 110.2
    }

    # LAST GAME: Celtics vs Heat (completed, home win)
    last_game = {
        'home_team': {
            'id': '1',
            'name': 'Boston Celtics',
            'abbrev': 'BOS',
            'score': 118
        },
        'away_team': {
            'id': '14',
            'name': 'Miami Heat',
            'abbrev': 'MIA',
            'score': 112
        },
        'date': '2025-01-13T19:30:00Z',
        'venue': {
            'name': 'TD Garden',
            'city': 'Boston',
            'state': 'MA'
        },
        'status': {
            'name': 'STATUS_FINAL',
            'detail': 'Final',
            'period': 4
        },
        'season': {'type': 2, 'year': '2025'},
        'competitions': [{
            'broadcasts': [
                {
                    'type': {'shortName': 'TV'},
                    'market': {'type': 'Home'},
                    'media': {'shortName': 'NBCSB'}
                }
            ],
            'attendance': 19156
        }]
    }

    last_opponent_stats = {
        'record': {'wins': 14, 'losses': 11, 'winPercent': 0.560},
        'rank': 8,
        'ppg': 109.5,
        'papg': 107.9
    }

    h2h = {
        'season_series': {
            'team_wins': 1,
            'opponent_wins': 0
        },
        'previous_game': {
            'date': 'November 15, 2024',
            'result': 'Win',
            'score': '118-112',
            'score_abbrev': 'W 118-112',
            'winner': 'Boston Celtics',
            'loser': 'Miami Heat',
            'location': 'home',
            'days_since': 59
        }
    }

    streaks = {
        'home_streak': 'W6',
        'away_streak': 'W2',
        'last_5_record': '4-1',
        'last_10_record': '8-2',
        'recent_form': 'WWLWW'
    }

    context = {
        'team_config': team_config,
        'team_stats': team_stats,
        'opponent_stats': current_opponent_stats,
        'h2h': h2h,
        'streaks': streaks,
        'head_coach': 'Joe Mazzulla',
        'player_leaders': {
            'basketball_top_scorer_name': 'Jayson Tatum',
            'basketball_top_scorer_ppg': '28.5',
            'basketball_top_rebounder_name': 'Kristaps Porzingis',
            'basketball_top_rebounder_rpg': '9.2',
            'basketball_top_assist_name': 'Jrue Holiday',
            'basketball_top_assist_apg': '7.8'
        },
        'epg_timezone': 'America/New_York',
        'game': current_game,
        'next_game': {
            'game': next_game,
            'opponent_stats': next_opponent_stats,
            'h2h': {},
            'streaks': {},
            'head_coach': 'Tyronn Lue',
            'player_leaders': {}
        },
        'last_game': {
            'game': last_game,
            'opponent_stats': last_opponent_stats,
            'h2h': h2h,
            'streaks': {},
            'head_coach': 'Erik Spoelstra',
            'player_leaders': {}
        }
    }

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

    if same_as_base and base != '':
        print("⚠️  ANALYSIS: All three values are IDENTICAL")
        print("   → This variable does NOT vary by game context")
        print("   → RECOMMENDATION: Remove .next and .last suffixes")
    elif base_next_same and base_last_same:
        print("⚠️  ANALYSIS: All values match when populated")
        print("   → RECOMMENDATION: Remove .next and .last suffixes")
    elif base != next_val or base != last_val:
        print("✓  ANALYSIS: Values differ across contexts")
        print("   → This variable IS game-specific")
        print("   → RECOMMENDATION: Keep .next and .last suffixes")
    else:
        print("?  ANALYSIS: All values empty or need more data")

    print()
    return same_as_base

if __name__ == '__main__':
    print("Generating test context with full data...")
    context = create_full_context()

    engine = TemplateEngine()
    variables = engine._build_variable_dict(context)

    # Get all unique base variable names (without suffixes)
    base_vars = sorted([k for k in variables.keys() if '.' not in k])

    print(f"\nTotal base variables: {len(base_vars)}")
    print(f"Total with suffixes: {len(variables)}")
    print("\nStarting variable-by-variable audit...\n")

    # Show first variable as example
    var_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    if var_num > 0 and var_num <= len(base_vars):
        show_variable(base_vars[var_num - 1], variables, var_num, len(base_vars))
    else:
        print(f"Usage: python3 variable_audit.py <number 1-{len(base_vars)}>")
        print(f"\nFirst 10 variables:")
        for i, var in enumerate(base_vars[:10], 1):
            print(f"  {i}. {var}")
