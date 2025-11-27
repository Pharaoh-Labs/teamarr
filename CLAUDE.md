# Teamarr - Dynamic EPG Generator for Sports Team Channels

## Project Overview
Teamarr generates XMLTV EPG data for sports team channels. It supports two modes:
1. **Team-based EPG** - Traditional mode: one team per channel, generates pregame/game/postgame/idle programs
2. **Event-based EPG** - New mode: Dispatcharr channel groups with streams named by matchup (e.g., "Panthers @ 49ers")

## Tech Stack
- **Backend**: Python/Flask (app.py)
- **Database**: SQLite (teamarr.db)
- **Frontend**: Jinja2 templates with vanilla JS
- **External APIs**: ESPN API (schedules, teams), Dispatcharr API (M3U accounts, channel groups)

## Key Directories
```
/srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr/
├── app.py                    # Main Flask app, all routes
├── database/                 # SQLite schema, migrations, CRUD
├── epg/                      # EPG generation engines
│   ├── orchestrator.py       # Team-based EPG orchestration
│   ├── xmltv_generator.py    # XMLTV output for team-based
│   ├── template_engine.py    # Team-based variable substitution
│   ├── team_matcher.py       # Extract teams from stream names
│   ├── event_matcher.py      # Find ESPN events by team matchup
│   ├── event_epg_generator.py    # XMLTV for event-based streams
│   ├── event_template_engine.py  # Event variable substitution
│   └── epg_consolidator.py   # Merge team + event EPGs
├── api/
│   ├── espn_client.py        # ESPN API wrapper
│   └── dispatcharr_client.py # Dispatcharr API client
├── templates/                # Jinja2 HTML templates
│   ├── template_form.html    # Template editor (team + event types)
│   ├── template_list.html    # Templates listing
│   ├── event_groups.html     # Event EPG groups management
│   └── ...
└── config/
    └── variables.json        # Template variable definitions
```

## Current Branch: `dev-withevents`

### Event-based EPG Feature Status

**Completed Phases:**
- Phase 1: Database schema for event_epg_groups table
- Phase 2: TeamMatcher - extracts team names from stream names using ESPN team database + user aliases
- Phase 3: EventMatcher - finds upcoming/live ESPN events between detected teams
- Phase 4: EventEPGGenerator - generates XMLTV for matched streams
- Phase 5: EPG Consolidator - merges event EPGs with team EPGs into final output
- Phase 6: API endpoints for Dispatcharr integration (accounts, groups, streams)
- Phase 7: UI for event groups management (partially complete)

**Phase 7 UI Details (Current Work):**
- Event Groups page at `/event-groups` - list and manage Dispatcharr groups
- Import modal to add groups from Dispatcharr
- Group filtering by M3U account
- Stream sorting (alphabetical)
- League dropdown with proper college conference fetching
- Templates support both "team" and "event" types
- Event templates: simplified description (single field, no conditions/fallbacks)
- Team templates: full complexity (multiple descriptions, conditions, priorities)
- Template form hides Conditions tab and Idle section for event templates
- Type column in templates list shows Team/Event badge

**Key Behaviors:**
- Event matching only works for **upcoming or in-progress** games (completed/FINAL games are filtered out)
- Stream names must contain both team names with a separator (e.g., "Panthers @ 49ers", "Giants vs Cowboys")
- TeamMatcher detects teams via ESPN database + user-defined aliases
- EventMatcher searches team schedules for matchups within ±7 days

## Running the Server
```bash
cd /srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr
python3 app.py
# Server runs on port 9195
```

## Template Types
- **Team templates**: Full-featured with pregame/postgame/idle periods, conditional descriptions, multiple fallbacks
- **Event templates**: Simplified - just title, description, pregame/postgame (no idle, no conditions, single description)

## Important Design Decisions
1. Event templates use a single description field (not the multi-fallback system team templates use)
2. Event matching skips completed games - EPG is for upcoming/live events only
3. EPG consolidation merges all sources into a single XML file for Plex/Jellyfin
4. Dispatcharr groups are filtered by M3U account to show only relevant groups

---

## Phase 8: Channel Lifecycle Management (Upcoming)

### Overview
When an event stream is matched, Teamarr will automatically create channels in Dispatcharr, assign the stream, set channel name/EPG, and manage the channel's lifecycle (creation timing, deletion timing).

### Feature Requirements

1. **Dynamic Channel Creation in Dispatcharr**
   - When a stream matches an ESPN event, create a channel via Dispatcharr API
   - Assign the matched stream to the new channel
   - Set channel name from event template's new `channel_name` field
   - Inject EPG data directly into the channel (tvg-id may not be needed)

2. **Channel Name in Event Templates**
   - Add `channel_name` field to event template creation/editing
   - Template variables available: `{home_team}`, `{away_team}`, `{league}`, etc.
   - Example: `{away_team} @ {home_team}` → "Giants @ Cowboys"

3. **Channel Lifecycle Settings (Per-Group)**
   - **Create Channel**: day of event, day before, 2 days before, etc.
   - **Delete Channel**: when stream no longer detected, end of game day, end of next day, etc.
   - Configured at the `event_epg_groups` level, not globally

4. **Track Created Channels**
   - New database table to track channels Teamarr creates
   - Fields: dispatcharr_channel_id, stream_id, event_id, created_at, scheduled_delete_at
   - Enables cleanup and management of Teamarr-created channels

5. **Channel Range / Starting Channel (Per-Group)**
   - Each event group has a `channel_start` or `channel_range_start`/`channel_range_end`
   - Channels created for this group use numbers within that range
   - Display in event groups summary table

### Database Changes Required

```sql
-- Add to event_epg_groups table
ALTER TABLE event_epg_groups ADD COLUMN channel_start INTEGER;
ALTER TABLE event_epg_groups ADD COLUMN channel_create_timing TEXT DEFAULT 'day_of';
   -- Values: 'day_of', 'day_before', '2_days_before', 'week_before'
ALTER TABLE event_epg_groups ADD COLUMN channel_delete_timing TEXT DEFAULT 'stream_removed';
   -- Values: 'stream_removed', 'end_of_day', 'end_of_next_day', 'manual'

-- New table: managed_channels
CREATE TABLE managed_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_epg_group_id INTEGER NOT NULL REFERENCES event_epg_groups(id),
    dispatcharr_channel_id INTEGER NOT NULL,
    dispatcharr_stream_id INTEGER NOT NULL,
    channel_number INTEGER,
    channel_name TEXT,
    espn_event_id TEXT,
    event_date TEXT,  -- YYYY-MM-DD
    scheduled_delete_at TIMESTAMP,
    deleted_at TIMESTAMP,
    UNIQUE(dispatcharr_channel_id)
);
```

### API Changes Required (Dispatcharr Client)

**Reference:** See `/mnt/nvme/scratch/channelidentifiarr/backend/app.py` for working implementation.

Need to add to `dispatcharr_client.py`:
```python
class ChannelManager:
    def create_channel(self, name, number, stream_ids, tvg_id=None, group_id=None, logo_id=None) -> Dict
    def update_channel(self, channel_id, data) -> Dict
    def delete_channel(self, channel_id) -> bool
    def get_channels(self) -> List[Dict]
    def get_channel_streams(self, channel_id) -> List[Dict]
```

**Dispatcharr Channel API Endpoints (confirmed from channelidentifiarr):**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/channels/channels/` | GET | List all channels (paginated) |
| `/api/channels/channels/` | POST | Create channel |
| `/api/channels/channels/{id}/` | PATCH | Update channel |
| `/api/channels/channels/{id}/` | DELETE | Delete channel |
| `/api/channels/channels/{id}/streams/` | GET | Get channel streams |

**Create Channel Payload:**
```python
{
    'name': 'Giants @ Cowboys',           # Channel name (required)
    'channel_number': '5001',             # Channel number (required)
    'tvg_id': 'teamarr-giants-cowboys',   # For XMLTV EPG matching
    'tvc_guide_stationid': None,          # Gracenote ID (not needed for us)
    'channel_group_id': 5,                # Optional group assignment
    'logo_id': 239,                       # Optional logo reference
    'streams': [stream_id]                # Stream IDs to attach
}
```

**Update Channel (stream assignment):**
```python
PATCH /api/channels/channels/{id}/
{'streams': [stream_id1, stream_id2]}   # Order = priority
```

**Key insight:** EPG is set via `tvg_id` field on channel creation - this should match our XMLTV output's channel ID.

### UI Changes Required

1. **Event Template Form** (`templates/template_form.html`)
   - Add "Channel Name" field for event templates
   - Template variable support with preview

2. **Event Groups Table** (`templates/event_epg.html`)
   - Add "Channel Start" column to summary table
   - Show lifecycle settings in expanded view or edit modal

3. **Event Group Edit/Import Modal**
   - Channel range/start field
   - Channel create timing dropdown
   - Channel delete timing dropdown

4. **Managed Channels View** (new or within event groups)
   - List channels Teamarr has created
   - Manual delete option
   - Status (active, scheduled for deletion)

### Implementation Phases

**Phase 8.1: Database & API Foundation**
- Add new columns to event_epg_groups
- Create managed_channels table
- Research Dispatcharr channel API endpoints
- Implement ChannelManager in dispatcharr_client.py

**Phase 8.2: Channel Creation Logic**
- Modify event EPG generation to create channels when matched
- Implement channel number allocation within group's range
- Track created channels in managed_channels table

**Phase 8.3: Channel Lifecycle Scheduler**
- Create timing check: should channel be created now?
- Delete timing check: should channel be deleted now?
- Background job or on-refresh check

**Phase 8.4: UI Updates**
- Add channel_name to event templates
- Add lifecycle settings to event groups UI
- Add channel range to event groups table
- Managed channels list view
- Dashboard: Show event-based managed channels alongside team channels

### What Might Need Work After Phase 8
- Test with upcoming games
- Better UI feedback for stream matching issues
- Scheduled refresh for event groups
- More event template variables (venue, broadcast network, etc.)
- Documentation/help text in UI
