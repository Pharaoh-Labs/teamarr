#!/usr/bin/env python3
"""
Extract configuration from legacy TeamArr database
"""
import sqlite3
import json

# Connect to legacy database
legacy_db = '/mnt/docker/stacks/teamarr/data/teamarr.db'
conn = sqlite3.connect(legacy_db)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get Pistons configuration
cursor.execute("SELECT * FROM teams WHERE id = 1")
pistons = cursor.fetchone()

print("=" * 80)
print("PISTONS CONFIGURATION (Legacy)")
print("=" * 80)
print()

# Basic info
print("[BASIC INFO]")
print(f"Team Name: {pistons['team_name']}")
print(f"League: {pistons['league']}")
print(f"Sport: {pistons['sport']}")
print(f"ESPN Team ID: {pistons['espn_team_id']}")
print(f"Channel ID: {pistons['channel_id']}")
print()

# Templates
print("[TEMPLATES]")
print(f"Title Format: {pistons['title_format']}")
print(f"Subtitle Template: {pistons['subtitle_template']}")
print(f"Description Template: {pistons['description_template']}")
print()

# Conditional Descriptions
print("[CONDITIONAL DESCRIPTIONS]")
description_options = json.loads(pistons['description_options'])
for idx, desc_opt in enumerate(description_options, 1):
    print(f"\n  Conditional #{idx}:")
    print(f"    Name: {desc_opt.get('name', 'N/A')}")
    print(f"    Condition: {desc_opt.get('condition', 'N/A')}")
    print(f"    Value: {desc_opt.get('condition_value', 'N/A')}")
    print(f"    Priority: {desc_opt.get('priority', 'N/A')}")
    print(f"    Template: {desc_opt.get('template', 'N/A')}")
    print(f"    Source: {desc_opt.get('source', 'N/A')}")
print()

# Filler settings
print("[FILLER - NO GAME]")
print(f"Enabled: {bool(pistons['no_game_enabled'])}")
print(f"Title: {pistons['no_game_title']}")
print(f"Description: {pistons['no_game_description']}")
print(f"Duration: {pistons['no_game_duration']} hours")
print()

print("[FILLER - PREGAME PERIODS]")
pregame_periods = json.loads(pistons['pregame_periods'])
for idx, period in enumerate(pregame_periods, 1):
    print(f"\n  Period #{idx}:")
    print(f"    Time Range: {period['end_hours_before']}h - {period['start_hours_before']}h before game")
    print(f"    Title: {period['title']}")
    print(f"    Description: {period['description']}")
print()

print("[FILLER - POSTGAME PERIODS]")
postgame_periods = json.loads(pistons['postgame_periods'])
for idx, period in enumerate(postgame_periods, 1):
    print(f"\n  Period #{idx}:")
    print(f"    Time Range: {period['start_hours_after']}h - {period['end_hours_after']}h after game")
    print(f"    Title: {period['title']}")
    print(f"    Description: {period['description']}")
print()

print("[FILLER - IDLE/BETWEEN GAMES]")
print(f"Enabled: {bool(pistons['idle_enabled'])}")
print(f"Title: {pistons['idle_title']}")
print(f"Description: {pistons['idle_description']}")
print()

# XMLTV settings
print("[XMLTV SETTINGS]")
flags = json.loads(pistons['flags'])
print(f"Flags: {flags}")
categories = json.loads(pistons['categories'])
print(f"Categories: {categories}")
print(f"Categories Apply To: {pistons['categories_apply_to']}")
print()

# Feature toggles
print("[FEATURE TOGGLES]")
print(f"Enable Records: {bool(pistons['enable_records'])}")
print(f"Enable Streaks: {bool(pistons['enable_streaks'])}")
print(f"Enable Head-to-Head: {bool(pistons['enable_head_to_head'])}")
print(f"Enable Standings: {bool(pistons['enable_standings'])}")
print(f"Enable Statistics: {bool(pistons['enable_statistics'])}")
print(f"Enable Players: {bool(pistons['enable_players'])}")
print()

# Game settings
print("[GAME SETTINGS]")
print(f"Game Duration: {pistons['game_duration']} hours")
print(f"Game Duration Mode: {pistons['game_duration_mode']}")
print(f"Max Program Hours: {pistons['max_program_hours']}")
print(f"Midnight Crossover: {pistons['midnight_crossover_mode']}")
print()

print("=" * 80)
print()

# Get all active teams
print("ACTIVE TEAMS")
print("=" * 80)
cursor.execute("SELECT id, team_name, league, sport, espn_team_id, channel_id FROM teams WHERE active = 1")
teams = cursor.fetchall()
for team in teams:
    print(f"{team['id']:2d}. {team['team_name']:30s} | {team['league']:4s} | {team['sport']:12s} | {team['channel_id']}")

print()
print(f"Total active teams: {len(teams)}")

conn.close()
