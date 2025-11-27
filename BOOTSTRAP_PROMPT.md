# Bootstrap Prompt for Teamarr Development

Copy and paste this to continue development:

---

I'm continuing development on Teamarr, a sports EPG generator. Read CLAUDE.md first for project context.

**Current branch:** `dev-withevents`

**What's been completed:**
- Event-based EPG feature (Phases 1-7) - allows generating EPG from Dispatcharr channel groups where streams are named by matchup (e.g., "Panthers @ 49ers")
- TeamMatcher extracts team names from stream names
- EventMatcher finds upcoming ESPN events between detected teams
- Event templates are simplified (single description, no conditions/fallbacks, no idle section)
- Team templates retain full complexity (multiple descriptions, conditions, priorities)
- UI at `/event-groups` for managing Dispatcharr groups
- EPG consolidation merges event EPGs with team EPGs

**Key files modified recently:**
- `templates/template_form.html` - Added event description handling (single input vs multiple fallbacks)
- `templates/template_list.html` - Added Type column (Team/Event badge)
- `epg/event_matcher.py` - Filters out completed/FINAL games (only matches upcoming/live)
- `epg/team_matcher.py` - Extracts teams from stream names
- `app.py` - API endpoints for event EPG

**Known behaviors:**
- Event matching only works for UPCOMING or IN-PROGRESS games
- Streams for completed games (like yesterday's MNF Panthers @ 49ers) won't match - this is intentional
- Stream names need both team names + separator (@ vs at) to be detected

**To run the server:**
```bash
cd /srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr
python3 app.py
# Runs on port 9195
```

**Current Focus: Phase 8 - Channel Lifecycle Management**

When an event stream is matched, Teamarr will automatically:
1. Create a channel in Dispatcharr via API
2. Assign the matched stream to the channel
3. Set channel name from event template
4. Manage channel lifecycle (create/delete timing per-group)

**Phase 8.1 (In Progress):** Database & API Foundation
- Add columns to event_epg_groups: channel_start, channel_create_timing, channel_delete_timing
- Create managed_channels table to track Teamarr-created channels
- Research Dispatcharr channel CRUD API endpoints
- Implement ChannelManager in dispatcharr_client.py

**Phase 8.2:** Channel Creation Logic
**Phase 8.3:** Channel Lifecycle Scheduler
**Phase 8.4:** UI Updates (channel_name in templates, lifecycle settings in groups)

See CLAUDE.md "Phase 8: Channel Lifecycle Management" for full details.

**Other items (lower priority):**
- Test with upcoming games
- Better UI feedback when streams don't match
- Scheduled refresh for event groups
- More event template variables (venue, broadcast network, etc.)
- Documentation/help text in UI

---
