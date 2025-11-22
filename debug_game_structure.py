#!/usr/bin/env python3
"""Debug - show actual game structure from ESPN API"""

import sys
sys.path.insert(0, '/srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr/teamarr-redux')

from api.espn_client import ESPNClient
import json

client = ESPNClient()

print("Fetching Celtics schedule...")
schedule = client.get_team_schedule('basketball', 'nba', '2', days_ahead=60)

if schedule and 'events' in schedule:
    events = schedule['events']
    print(f"Found {len(events)} events\n")

    # Show first event structure
    if events:
        print("="*80)
        print("FIRST EVENT STRUCTURE:")
        print("="*80)
        print(json.dumps(events[0], indent=2)[:3000])
        print("\n...")

        # Check for home_team/away_team
        print("\n" + "="*80)
        print("CHECKING FOR home_team/away_team:")
        print("="*80)
        print(f"Has 'home_team' key: {'home_team' in events[0]}")
        print(f"Has 'away_team' key: {'away_team' in events[0]}")
        print(f"Has 'competitions' key: {'competitions' in events[0]}")

        if 'competitions' in events[0]:
            comp = events[0]['competitions'][0]
            print(f"\nCompetition keys: {list(comp.keys())}")
            if 'competitors' in comp:
                print(f"Has 'competitors': True")
                print(f"Number of competitors: {len(comp['competitors'])}")
                print(f"\nFirst competitor structure:")
                print(json.dumps(comp['competitors'][0], indent=2))
