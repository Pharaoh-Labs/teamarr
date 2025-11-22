# TeamArr v1.0.0 Migration Plan
## Template-Based Architecture (Breaking Change)

**Date**: 2025-11-23
**Version**: 0.x.x → 1.0.0
**Migration Method**: Safe Branch-Based Replacement
**⚠️ BREAKING CHANGE**: No database migration - users must start fresh

---

## Pre-Migration Checklist

- [ ] All current changes committed to git
- [ ] Old app process stopped
- [ ] Backup created (database + EPG files)
- [ ] Users notified of breaking change
- [ ] README updated with migration notice

---

## Step 1: Backup Current State

```bash
cd /srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr

# Create backup directory
mkdir -p ../teamarr-backup-$(date +%Y%m%d)

# Backup database and generated EPG files
cp teamarr.db ../teamarr-backup-$(date +%Y%m%d)/
cp -r data ../teamarr-backup-$(date +%Y%m%d)/ 2>/dev/null || true
cp epg.xml ../teamarr-backup-$(date +%Y%m%d)/ 2>/dev/null || true

# Verify backup
ls -lah ../teamarr-backup-$(date +%Y%m%d)/
```

**Expected**: Backup directory created with database copy

---

## Step 2: Stop Old Application

```bash
# Find and stop all running TeamArr processes
ps aux | grep -E "python.*app.py|teamarr" | grep -v grep

# Kill old app (find PID from above, replace XXXXX)
# kill XXXXX

# Or stop via Docker if running in container
docker stop teamarr 2>/dev/null || true
```

**Expected**: No teamarr processes running, port 9195 freed

---

## Step 3: Create Git Backup Branch

```bash
cd /srv/dev-disk-by-uuid-c332869f-d034-472c-a641-ccf1f28e52d6/scratch/teamarr

# Ensure we're on dev branch
git checkout dev

# Stage all current changes
git add -A

# Commit current state
git commit -m "Pre-v1.0.0 state - Team-centric architecture (final)"

# Create backup branch
git branch old-team-centric-v0.x

# Push to remote if using GitHub
# git push origin old-team-centric-v0.x

# Verify branch created
git branch -a
```

**Expected**: New branch `old-team-centric-v0.x` created with current code

---

## Step 4: Remove Old Files (Keep .git)

```bash
# Remove everything except .git and teamarr-redux
find . -maxdepth 1 \
  ! -name '.git' \
  ! -name '.' \
  ! -name '..' \
  ! -name 'teamarr-redux' \
  -exec rm -rf {} + 2>/dev/null || true

# Verify only .git and teamarr-redux remain
ls -la
```

**Expected**: Only `.git/` and `teamarr-redux/` directories present

---

## Step 5: Move Redux Files to Root

```bash
# Move all files from teamarr-redux to parent
mv teamarr-redux/* .
mv teamarr-redux/.* . 2>/dev/null || true

# Remove empty teamarr-redux directory
rmdir teamarr-redux

# Verify files moved
ls -la
```

**Expected**: All redux files now in root, teamarr-redux gone

---

## Step 6: Update Configuration Files

Already done in redux, but verify:

```bash
# Verify port is 9195
grep -n "port.*9195\|PORT.*9195" app.py

# Verify XMLTV generator URL
grep -n "9195" app.py database/schema.sql

# Verify TZ environment sync
grep -n "TZ" database/__init__.py
```

**Expected**:
- `app.py` line 50: `http://localhost:9195`
- `app.py` line 1564: `PORT`, 9195`
- `database/__init__.py`: TZ sync code present

---

## Step 7: Update README with Breaking Change Notice

See next step for README content.

---

## Step 8: Commit New Version

```bash
# Stage all new files
git add -A

# Commit v1.0.0
git commit -m "Release v1.0.0 - Template-Based Architecture

BREAKING CHANGE: Complete architectural refactor to template-based model

Major Changes:
- Replaced team-centric with template-based architecture
- Templates are now reusable across multiple teams
- No database migration - users must start fresh
- Added comprehensive variable suffix system (.next, .last)
- 117 base variables (252 with suffixes)
- Reorganized UI with better variable categorization
- Added TZ environment variable sync
- Consolidated conditional descriptions

Migration:
- Users on v0.x MUST delete existing database
- Fresh start required - no migration path
- See README for breaking change notice

Co-Authored-By: Claude <noreply@anthropic.com>"

# Tag release
git tag -a v1.0.0 -m "v1.0.0 - Template-Based Architecture (Breaking Change)"

# Verify commit
git log --oneline -5
git tag -l
```

**Expected**: New commit created on dev branch, tagged v1.0.0

---

## Step 9: Initialize Fresh Database

```bash
# Remove old database if exists
rm -f teamarr.db

# App will auto-initialize on first run with TZ from environment
# Or manually initialize:
python3 -c "from database import init_database; init_database()"
```

**Expected**: Fresh `teamarr.db` created with v1.0.0 schema

---

## Step 10: Start New Application

```bash
# Start app (will run on port 9195)
python3 app.py

# Or via Docker
# docker-compose up -d

# Verify running
curl -s http://localhost:9195/ | grep -o "<title>.*</title>"
```

**Expected**: App running on port 9195, homepage loads

---

## Step 11: Verification Tests

1. **Dashboard loads**: http://localhost:9195/
2. **Create template**: http://localhost:9195/templates/add
   - Verify variable helper shows suffix guide
   - Verify 5 categories display (Teams, Games, Team Stats, Roster, Betting)
   - Verify conditional dropdown has new conditions
3. **Import team**: http://localhost:9195/teams/import
   - Import test team from ESPN
4. **Assign template**: http://localhost:9195/teams
   - Assign template to imported team
5. **Generate EPG**: Click "Generate EPG" button
6. **Download EPG**: Verify XMLTV file downloads
7. **Settings**: http://localhost:9195/settings
   - Verify timezone matches TZ env var

---

## Step 12: Push to Remote (Optional)

```bash
# Push dev branch
git push origin dev

# Push tag
git push origin v1.0.0

# Push backup branch
git push origin old-team-centric-v0.x
```

---

## Rollback Procedure (If Needed)

```bash
# Stop new app
kill <PID>  # or docker stop teamarr

# Checkout old branch
git checkout old-team-centric-v0.x

# Restore backup database
cp ../teamarr-backup-YYYYMMDD/teamarr.db .

# Start old app
python3 app.py
```

---

## User Migration Instructions (For README)

### ⚠️ BREAKING CHANGE: v0.x → v1.0.0

**TeamArr v1.0.0 is a complete architectural rewrite. No database migration is available.**

**For users on v0.x versions:**

1. **Stop your current TeamArr instance**
2. **Backup your data** (optional - for reference only):
   ```bash
   cp teamarr.db teamarr-backup.db
   cp epg.xml epg-backup.xml
   ```
3. **Delete the old database**:
   ```bash
   rm teamarr.db
   ```
4. **Update to v1.0.0** (pull latest, rebuild container, etc.)
5. **Start TeamArr** - fresh database will be created automatically
6. **Reconfigure from scratch**:
   - Create templates (new concept - reusable across teams)
   - Import your teams from ESPN
   - Assign templates to teams
   - Configure settings

**What's Different:**
- **Templates**: Formatting rules are now separate from teams
- **Variables**: 117 base variables with .next/.last suffix support (252 total)
- **Organization**: Variables grouped into 5 logical categories
- **Conditionals**: Streamlined condition types
- **No per-team timezones**: Single global timezone (synced from TZ env var)

**Why No Migration:**
The database schema is fundamentally different. The old team-centric model stored all settings per-team. The new template-based model separates formatting (templates) from team identity.

---

## Post-Migration Checklist

- [ ] App running on port 9195
- [ ] Dashboard accessible
- [ ] Template creation works
- [ ] Team import works
- [ ] EPG generation successful
- [ ] XMLTV file valid
- [ ] Settings timezone correct
- [ ] Docker compose compatible
- [ ] README updated
- [ ] CHANGELOG updated
- [ ] Version bumped to 1.0.0
- [ ] Git tagged
- [ ] Users notified

---

## Migration Support

**Old Code**: Available on branch `old-team-centric-v0.x`
**Backup Location**: `../teamarr-backup-YYYYMMDD/`
**Rollback**: Checkout old branch, restore backup database

---

## Timeline Estimate

- **Preparation**: 5 minutes
- **Backup**: 2 minutes
- **Migration**: 10 minutes
- **Testing**: 15 minutes
- **Total**: ~30 minutes

---

## Notes

- Database file stays named `teamarr.db` (same as before)
- EPG output path stays same (`epg.xml` or configured path)
- Docker volume mounts unchanged
- Port unchanged (9195)
- Only breaking change is database schema
