#!/usr/bin/env python3
"""
Update team logos for existing teams in the database
"""

import sqlite3
from api.espn_client import ESPNClient

def update_team_logos():
    """Fetch and update logos for all teams missing logo URLs"""

    conn = sqlite3.connect('teamarr.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all teams (check for missing logos OR missing slugs)
    teams = cursor.execute("""
        SELECT id, espn_team_id, league, sport, team_name
        FROM teams
        WHERE team_logo_url IS NULL OR team_logo_url = '' OR team_slug IS NULL OR team_slug = ''
    """).fetchall()

    if not teams:
        print("No teams need logo updates")
        return

    print(f"Found {len(teams)} teams needing logo updates")

    espn = ESPNClient()
    updated_count = 0
    failed_count = 0

    # Group teams by league for efficient API calls
    teams_by_league = {}
    for team in teams:
        league_key = (team['sport'], team['league'])
        if league_key not in teams_by_league:
            teams_by_league[league_key] = []
        teams_by_league[league_key].append(team)

    # Process each league
    for (sport, league), league_teams in teams_by_league.items():
        print(f"\nProcessing {league.upper()} ({len(league_teams)} teams)...")

        try:
            # Get league mapping from database
            league_info = cursor.execute("""
                SELECT api_path FROM league_config WHERE league_code = ?
            """, (league,)).fetchone()

            if not league_info:
                print(f"  WARNING: League {league} not found in league_config")
                failed_count += len(league_teams)
                continue

            # Extract league identifier from api_path
            league_identifier = league_info['api_path'].split('/')[-1]

            # Fetch all teams from ESPN
            espn_teams = espn.get_league_teams(sport, league_identifier)

            if not espn_teams:
                print(f"  WARNING: No teams returned from ESPN for {league}")
                failed_count += len(league_teams)
                continue

            # Create lookup dict by ESPN team ID
            espn_lookup = {str(t['id']): t for t in espn_teams}

            # Update each team
            for team in league_teams:
                espn_team_id = str(team['espn_team_id'])

                if espn_team_id in espn_lookup:
                    espn_data = espn_lookup[espn_team_id]
                    logo_url = espn_data.get('logo')
                    color = espn_data.get('color')
                    slug = espn_data.get('slug')

                    if logo_url or slug:
                        cursor.execute("""
                            UPDATE teams
                            SET team_logo_url = ?, team_color = ?, team_slug = ?
                            WHERE id = ?
                        """, (logo_url, color, slug, team['id']))

                        print(f"  ✅ Updated {team['team_name']}")
                        updated_count += 1
                    else:
                        print(f"  ⚠️  No logo/slug for {team['team_name']}")
                        failed_count += 1
                else:
                    print(f"  ❌ Not found in ESPN: {team['team_name']} (ID: {espn_team_id})")
                    failed_count += 1

        except Exception as e:
            print(f"  ERROR processing {league}: {e}")
            failed_count += len(league_teams)

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Summary:")
    print(f"  Updated: {updated_count}")
    print(f"  Failed: {failed_count}")
    print(f"{'='*50}")

if __name__ == '__main__':
    update_team_logos()
