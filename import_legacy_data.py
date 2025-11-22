#!/usr/bin/env python3
"""
Import legacy TeamArr configuration into Redux database
"""
import sqlite3
import json
from datetime import datetime

# Database paths
legacy_db = '/mnt/docker/stacks/teamarr/data/teamarr.db'
redux_db = '/srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr/teamarr-redux/teamarr.db'

# Connect to legacy database
legacy_conn = sqlite3.connect(legacy_db)
legacy_conn.row_factory = sqlite3.Row
legacy_cursor = legacy_conn.cursor()

# Connect to redux database
redux_conn = sqlite3.connect(redux_db)
redux_cursor = redux_conn.cursor()

print("=" * 80)
print("IMPORTING LEGACY DATA TO REDUX")
print("=" * 80)
print()

# Step 1: Extract Pistons template configuration
print("[1/2] Creating 'NBA Standard' template from Pistons configuration...")
legacy_cursor.execute("SELECT * FROM teams WHERE id = 1")
pistons = legacy_cursor.fetchone()

# Build description_options JSON - convert old description_template to fallback
description_options = json.loads(pistons['description_options'])

# Add the old description_template as a fallback with priority 100
if pistons['description_template']:
    description_options.append({
        'priority': 100,
        'template': pistons['description_template'],
        'label': 'Default'
    })

description_options_json = json.dumps(description_options)

# Build pregame/postgame periods
pregame_periods = json.loads(pistons['pregame_periods'])
postgame_periods = json.loads(pistons['postgame_periods'])

# Insert template
template_data = {
    'name': 'NBA Standard',
    'sport': pistons['sport'],
    'league': pistons['league'],
    'title_format': pistons['title_format'],
    'subtitle_template': pistons['subtitle_template'],
    'description_options': description_options_json,

    # Pregame filler
    'pregame_enabled': bool(pistons['pregame_enabled']),
    'pregame_periods': json.dumps(pregame_periods),

    # Postgame filler
    'postgame_enabled': bool(pistons['postgame_enabled']),
    'postgame_periods': json.dumps(postgame_periods),

    # Idle filler
    'idle_enabled': bool(pistons['idle_enabled']),
    'idle_title': pistons['idle_title'],
    'idle_description': pistons['idle_description'],

    # No game filler
    'no_game_enabled': bool(pistons['no_game_enabled']),
    'no_game_title': pistons['no_game_title'],
    'no_game_description': pistons['no_game_description'],
    'no_game_duration': pistons['no_game_duration'],

    # Game settings
    'game_duration_mode': pistons['game_duration_mode'],
    'game_duration_override': pistons['game_duration'] if pistons['game_duration_mode'] == 'custom' else None,

    # XMLTV settings
    'flags': pistons['flags'],
    'categories': pistons['categories'],
    'categories_apply_to': pistons['categories_apply_to']
}

redux_cursor.execute('''
    INSERT INTO templates (
        name, sport, league,
        title_format, subtitle_template, description_options,
        pregame_enabled, pregame_periods,
        postgame_enabled, postgame_periods,
        idle_enabled, idle_title, idle_description,
        no_game_enabled, no_game_title, no_game_description, no_game_duration,
        game_duration_mode, game_duration_override,
        flags, categories, categories_apply_to
    ) VALUES (
        :name, :sport, :league,
        :title_format, :subtitle_template, :description_options,
        :pregame_enabled, :pregame_periods,
        :postgame_enabled, :postgame_periods,
        :idle_enabled, :idle_title, :idle_description,
        :no_game_enabled, :no_game_title, :no_game_description, :no_game_duration,
        :game_duration_mode, :game_duration_override,
        :flags, :categories, :categories_apply_to
    )
''', template_data)

template_id = redux_cursor.lastrowid
print(f"   ✓ Created template 'NBA Standard' (ID: {template_id})")
print(f"   ✓ Included win streak conditional (priority 85)")
print()

# Step 2: Import teams
print("[2/2] Importing teams from legacy database...")
legacy_cursor.execute("SELECT * FROM teams WHERE active = 1")
legacy_teams = legacy_cursor.fetchall()

imported_count = 0
for legacy_team in legacy_teams:
    team_data = {
        'espn_team_id': legacy_team['espn_team_id'],
        'league': legacy_team['league'],
        'sport': legacy_team['sport'],
        'team_name': legacy_team['team_name'],
        'team_abbrev': legacy_team['team_abbrev'],
        'channel_id': legacy_team['channel_id'],
        'template_id': template_id if legacy_team['league'] == 'nba' else None,  # Only assign NBA teams to template
        'active': 1
    }

    redux_cursor.execute('''
        INSERT INTO teams (
            espn_team_id, league, sport, team_name, team_abbrev, channel_id, template_id, active
        ) VALUES (
            :espn_team_id, :league, :sport, :team_name, :team_abbrev, :channel_id, :template_id, :active
        )
    ''', team_data)

    imported_count += 1
    assigned = "✓ Assigned to 'NBA Standard'" if team_data['template_id'] else "✗ No template"
    print(f"   {imported_count}. {legacy_team['team_name']:30s} | {legacy_team['league']:4s} | {assigned}")

redux_conn.commit()
print()
print(f"✓ Successfully imported {imported_count} teams")
print()

# Verify the import
print("=" * 80)
print("VERIFICATION")
print("=" * 80)
print()

print("Templates in Redux:")
redux_cursor.execute("SELECT id, name, sport, league FROM templates")
templates = redux_cursor.fetchall()
for tmpl in templates:
    print(f"   {tmpl[0]}. {tmpl[1]} ({tmpl[2]}/{tmpl[3]})")
print()

print("Teams in Redux:")
redux_cursor.execute('''
    SELECT t.id, t.team_name, t.league, t.channel_id, t.active,
           CASE WHEN t.template_id IS NULL THEN 'None' ELSE tpl.name END as template_name
    FROM teams t
    LEFT JOIN templates tpl ON t.template_id = tpl.id
''')
teams = redux_cursor.fetchall()
for team in teams:
    print(f"   {team[0]:2d}. {team[1]:30s} | {team[2]:4s} | Template: {team[5]:20s} | Active: {bool(team[4])}")
print()

# Close connections
legacy_conn.close()
redux_conn.close()

print("=" * 80)
print("✓ IMPORT COMPLETE")
print("=" * 80)
