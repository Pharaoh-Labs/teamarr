# Agent Instructions - Teamarr

## Overview

Sports EPG generator. Uses **bd (beads)** for issue tracking. Start with `bd ready`.

## CRITICAL: Database Safety

**NEVER delete `teamarr.db` or `data/teamarr.db`.** The database contains user-configured teams, templates, settings, and history that cannot be recreated. Schema changes use migrations (`INSERT OR REPLACE`, `ALTER TABLE`) - deleting the database is NEVER required and will cause data loss.

**Stack**: Python 3.11+, FastAPI, SQLite | Frontend: React + TypeScript + Vite + Tailwind

## Start of Session

1. Re-read this file and follow it exactly
2. Switch to `dev` branch: `git checkout dev && git pull`
3. Check for work: `bd ready`

If you forget this workflow after a context compaction, re-read this file before continuing.

## Local Testing

Run `./dev.sh` to start both servers in one terminal:

```bash
./dev.sh                 # fast restart — skips cache refresh
./dev.sh --update-cache  # restart with full cache refresh
```

- **Backend** (FastAPI): `http://localhost:9195` — Python venv, `app.py`
- **Frontend** (Vite HMR): `http://localhost:5173` — proxies `/api` → `:9195`

Use `:5173` during development for hot-reload. `Ctrl+C` stops both.
Re-running `./dev.sh` kills existing servers first, so it doubles as a restart.

By default the script skips the startup cache refresh for fast restarts. Pass `--update-cache` when you need fresh team/league data from providers. Cache can also be refreshed manually via the UI button.

**Always use `./dev.sh` to start or restart the dev environment.** It handles cleanup of old processes automatically.

**When to restart:**
- After making backend (Python) code changes
- If Playwright browser automation can't connect to `localhost:5173`
- After schema or configuration changes

## Quick Reference Commands

```bash
bd ready                              # Find available work
bd show <id>                          # View issue details
bd update <id> --status in_progress   # Claim work
bd close <id>                         # Complete work
bd sync                               # Sync beads data
```

## Development Workflow

**Critical:** Work from `dev` branch, not `main`.

### Development Steps

1. **Check for work**: `bd ready` or `bd list`
2. **Claim work**: `bd update <id> --status in_progress`
3. **Implement the change**
4. **Review docs impact** (MANDATORY consideration — not every change needs doc updates, but every change must be *evaluated* against the Documentation Updates table below). If the change touches user-visible behavior, template variables, schema, providers, config, API endpoints, or changes a count/version referenced in docs, update the relevant page(s) in the same commit or a paired commit. Do not wait for the user to prompt.
5. **Run quality gates** (MANDATORY when shipping):
   ```bash
   ruff check teamarr/
   pytest tests/ -v
   cd frontend && npm run build
   ```
6. **Close the bead**: `bd close <id>`
7. **Push to dev** (MANDATORY):
   ```bash
   git add <changed-files>
   git commit -m "Brief description"
   git push origin dev
   ```

**Critical shipping rules:**
- Work is incomplete until `git push` succeeds
- Never stop before pushing—it leaves work stranded locally
- Never say "ready to push when you are"—YOU must push

### Roadmap & Feature Planning

Use beads epics to plan larger features:

```bash
bd create "Feature name" --type epic --label roadmap
bd create "Implementation step 1" --parent <epic-id>
bd create "Implementation step 2" --parent <epic-id>
bd dep add <step2-id> <step1-id>    # step 2 blocked by step 1
```

When asked to plan a feature, create an epic with implementation beads that have proper blockers and predecessors. Use `bd list --label roadmap` to see the roadmap.

### Release Workflow (`/release`)

When the user says **"release"**, **"/release"**, or **"version bump"**, execute this workflow:

1. **Determine scope** — `git log origin/main..origin/dev --oneline` to see all commits in the release
2. **Ask version** — suggest patch (x.y.Z) vs minor (x.Y.0) based on scope. User decides.
3. **Quality gates** (MANDATORY):
   ```bash
   source .venv/bin/activate
   ruff check teamarr/
   pytest tests/ -v
   cd frontend && npm run build
   ```
4. **Version bump** — edit `pyproject.toml` line 7, commit "Bump version to x.y.z"
5. **Push dev** — `git push origin dev`
6. **Merge to main** — fast-forward merge:
   ```bash
   git checkout main && git pull origin main
   git merge dev --no-edit
   git push origin main
   git checkout dev
   ```
7. **Create GitHub release** — `gh release create v<version> --repo Pharaoh-Labs/teamarr --target main` with summarized release notes (not commit-by-commit — group into categories)
8. **Generate Discord changelog** — use the Release Template below, output ready to paste
9. **Update plans/STATUS.md** — add release to changelog, update version

**Rules:**
- Never release with failing tests or lint errors
- Release notes should be human-readable summaries, not raw commit messages
- Group related commits into single bullet points

## Changelog Format

When asked for a changelog, **always** produce Discord-ready markdown. Two templates:

### Dev Push Template

Get version from `pyproject.toml` line 7, append `-dev+<short_hash>` of HEAD commit.

```
## 🚀 v<version>-dev+<hash> — <YYYY-MM-DD>

🐛 **Bug Fixes**
- <one-liner> (#issue) (`hash`)

✨ **New Features**
- <one-liner> (#issue) (`hash`)

⚡ **Enhancements**
- <one-liner> (#issue) (`hash`)

🎨 **UI/UX**
- <one-liner> (#issue) (`hash`)

🔧 **Under the Hood**
- <one-liner> — thanks @contributor (#PR) (`hash`)
```

### Release Template

```
## 🎉 v<version> — <YYYY-MM-DD>

🐛 **Bug Fixes**
- <one-liner> (#issue)

✨ **New Features**
- <one-liner> (#issue)

⚡ **Enhancements**
- <one-liner> (#issue)

🎨 **UI/UX**
- <one-liner> (#issue)

🔧 **Under the Hood**
- <one-liner> — thanks @contributor (#PR)
```

### Rules
- Discord markdown (## headers, **bold**, \`code\`)
- Categories (in order): 🐛 Bug Fixes, ✨ New Features, ⚡ Enhancements, 🎨 UI/UX, 🔧 Under the Hood
- **Omit empty categories** — only include sections that have items
- Dev pushes include commit hashes; releases do not
- **ALWAYS include issue numbers** — append `(#123)` to items that close or relate to a GitHub issue
- **ALWAYS credit contributors** — append `— thanks @username (#PR)` for community PR contributions
- Each item is one concise line — no multi-line descriptions
- No extra commentary — just the changelog block ready to paste

## Git Remote & Preferences

**Single remote:**
| Remote | Repo | Purpose |
|--------|------|---------|
| `origin` | `Pharaoh-Labs/teamarr` | All development, releases, and PRs |

**Rules:**
- Push to `origin dev` after completing work
- No commit watermarks or co-authored-by
- Concise, focused commit messages

## Documentation Updates

**Part of every development cycle.** After implementing any change, check this table *before* running quality gates. If a row matches, updating the listed docs is as much a part of the task as the code itself — don't defer it to a future sweep and don't wait for the user to prompt. Docs commits can ride in the same commit as the code or a paired follow-up; either way, they ship together.

| Change Type | Update |
|-------------|--------|
| New/renamed/removed template variable | `teamarr/templates/variables/` docstring AND `docs/guide/templates/variables.md` AND variable-count claims in `docs/guide/templates/variables.md`, `docs/reference/architecture/template-engine.md`, `docs/index.md`, and `CLAUDE.md` ("Key Subsystems") |
| New/renamed/removed condition evaluator | `teamarr/templates/conditions.py` docstring AND `docs/guide/templates/conditions.md` AND condition-count claims |
| New/renamed/removed league | `INSERT OR REPLACE INTO leagues` in `schema.sql` AND the appropriate sport section of `docs/reference/supported-leagues.md` AND league-count claims in `docs/reference/supported-leagues.md`, `docs/reference/index.md`, `docs/index.md`, and `docs/reference/providers/<provider>.md` |
| New/renamed sport | `INSERT INTO sports` in `schema.sql` AND `docs/reference/supported-leagues.md` sport list AND sport-count claims |
| New API endpoint | Route docstring AND OpenAPI (auto) AND relevant `docs/reference/architecture/*.md` if the endpoint shape changes subsystem behavior |
| New column | `CREATE TABLE` in `schema.sql` (reconciliation handles upgrades); no doc update needed unless the column is user-visible |
| Data migration | Versioned block in `_run_migrations()`, bump `schema_version` DEFAULT, AND update schema version in `docs/reference/architecture/migrations.md` |
| New provider | Architecture section in this file AND `docs/reference/providers/<name>.md` (new file) AND `docs/reference/supported-leagues.md` provider table |
| Config/settings change | `README.md` if user-facing, AND relevant `docs/guide/settings/*.md` page |
| New feature (user-visible) | README Features section AND appropriate `docs/guide/**` page; consider creating a guide page if substantial |
| Feature removal | Remove from docs (don't leave stale references); add to release notes |

If the change touches a count referenced in docs (variables, leagues, sports, conditions, schema version), grep for the old number across `docs/`, `CLAUDE.md`, and `README.md` — don't fix just one occurrence.

Documentation epic: `bd list --parent teamarrv2-nv4`

## Single Source of Truth

| What | Where |
|------|-------|
| Version | `pyproject.toml` line 7 |
| Dependencies | `pyproject.toml` (ranges) + `uv.lock` (pinned, used by the Docker build) — run `uv lock` after any dependency change or `--frozen` builds fail |
| League configs | `teamarr/database/schema.sql` |
| Schema version | `teamarr/database/schema.sql` (v76) |
| Schema reconciliation | `teamarr/database/reconciliation.py` |
| Provider registration | `teamarr/providers/__init__.py` |

## Architecture

```
API Layer        → teamarr/api/routes/ (18 modules)
Consumer Layer   → teamarr/consumers/ (orchestrator, team_epg, event_epg, cache/, lifecycle/, matching/)
Service Layer    → teamarr/services/sports_data.py
Provider Layer   → teamarr/providers/ (espn, hockeytech, mlbstats, tsdb)
```

**Providers** (lower priority = tried first):
- ESPN (0) - Primary, most leagues
- Squiggle (30) - AFL (Australian Football League); free, no key required
- MLB Stats (40) - MiLB (Triple-A through Rookie)
- HockeyTech (50) - CHL, AHL, PWHL, USHL
- TSDB (100) - Cricket, rugby, boxing, Scandinavian leagues, uru.2

**Dispatcharr Sync Reliability** (`lifecycle/service.py`):
All `update_channel` calls go through `_safe_update_channel`, which checks `OperationResult.success` before persisting to local DB. On API failure, the DB stays unchanged so drift is re-detected on the next generation run. Profile sync also compares against Dispatcharr's actual state (`current_channel.channel_profile_ids`) for self-healing. Reconciliation (`reconciliation.py`) detects stream and profile drift as additional drift fields.

## Key Subsystems

**Template Engine** (`teamarr/templates/`):
- 226 variables in `variables/` (19 categories)
- 23 condition evaluators in `conditions.py`
- Suffix rules: `.next`, `.last` for multi-game scenarios
- Template scope: each variable is tagged `TemplateScope.ALL` / `TEAM_ONLY` / `EVENT_ONLY` — gates variable picker by template type via `GET /variables?template_type=…`

**Dynamic Groups** (`teamarr/consumers/lifecycle/dynamic_resolver.py`):
- `{sport}` and `{league}` wildcards
- Auto-creates in Dispatcharr

**Per-Source Matching Types** (epic `teamarrv2-ahow`):
- Each source declares which matching pipeline(s) it runs — three independent booleans on `event_epg_groups`: `name_match_enabled` (Stream Name → TEAM_VS_TEAM/EVENT_CARD/RACING categories), `team_streams_enabled` (Team → TEAM_ONLY), `epg_match_enabled` (EPG). Multi-select; ≥1 required (enforced in `api/routes/groups.py::require_matching_type`).
- Gating is by **category at the matcher router** (`matcher.py::_match_single`, reason `name_match_disabled`) — classification always runs so the types stay independent; never skip `classify_stream`. `name_match_enabled` defaults 1 (DEFAULT-1 column backfills existing sources). The hidden `is_channel_source` group is name-off (EPG/team only).
- UI: three toggles on add/edit/bulk-add/bulk-edit; color-coded Sources badges (Stream Name=sky, Team=emerald, EPG=violet). The Matched-column coverage % shows only when Stream Name is on (Team/EPG fan one stream → many events).

**EPG Program Matching** (epic `teamarrv2-183`, `teamarr/consumers/matching/epg_*.py`):
- Matches static-named linear channels (ESPN, FS1) to events via Dispatcharr's program guide (`GET /api/epg/programs/search/`, feature-detected, Dispatcharr 0.24.0+), then time-shares one stream across many event channels (attach/detach window per program).
- Opt-in: per-group `epg_match_enabled` only (no global switch as of eqz/3lp1 — EPG matching is always available; each event-group opts in). Global tuning (attach/detach buffers, `epg_stream_pre/post_buffer_minutes`, default 60) lives on the **Matching** page (`/matching`, `EpgMatchingSettings` component) as of the v2.7.0 IA overhaul — not Settings. Per-group flag also sets `skip_builtin` so static names survive filtering.
- Channel-source mode (183.9, `epg_channel_source_enabled`): additive source from streams curated onto Dispatcharr channels (each channel's own EPG), run as a hidden system group (`is_channel_source`, `ensure_channel_source_group`); excludes Teamarr's own channels and dedupes streams already in EPG-match M3U groups. Candidate builder: `_fetch_channel_source_streams`.
- `epg_resolver.py` bridges the stream `tvg_id` → program `tvg_id` namespace gap via a cascade: direct tvg_id → curated channel `epg_data_id` → strict name match (does NOT require an EPG-linked channel). `_Teamarr` source excluded.
- `epg_index.py` fetches by resolved tvg_id, keys by stream tvg_id; `epg_matcher.py` routes program title+sub_title (pipe-joined) through `classify_stream → TeamMatcher`.
- `MatchMethod.EPG` persisted to `managed_channel_streams.match_method` → drives the `epg_match` stream-ordering rule. EPG-matched groups show an "EPG Matched" badge.
- Docs: `docs/guide/epg-matching.md`.

## Plans & Roadmap

Feature planning lives in beads: `bd list --label roadmap`

Legacy plans in `plans/` (gitignored) may have additional context.

## Code Health Audit (`teamarrv2-5hq`)

**Cyclical epic for keeping the codebase clean.** Run with: `audit`

When the user says **"audit"**, claim the next open child bead under `teamarrv2-5hq` and run the full audit:

1. **Dead API endpoints** — cross-reference every route in `teamarr/api/routes/` against the ENTIRE `frontend/src/` directory (not just `api/` — the frontend uses both structured api clients AND direct `fetch()` calls in pages/components) and backend callers. Only flag as dead if zero hits across all search patterns.
2. **Dead frontend code** — find unused exports in `frontend/src/api/`, `frontend/src/hooks/`, `frontend/src/components/`. Check for dynamic imports and lazy loading in `App.tsx` before flagging components as dead.
3. **Layer separation** — routes should only do request/response; no direct DB queries (`conn.execute`, `cursor`) in routes. Business logic belongs in services/consumers.
4. **Code quality** — god functions (200+ lines), deep nesting (4+ levels), inconsistent logging, magic numbers.
5. **Frontend hygiene** — unused components, dead hooks, stale API client functions.

6. **Test coverage before pruning** — before removing ANY code marked for pruning, verify:
   - Run `pytest tests/ -v` to confirm all existing tests pass first.
   - Search for callers/importers one more time (grep the entire codebase, not just obvious locations).
   - Check git blame — if code was added recently, it may be WIP or needed for an upcoming feature. Ask the user before removing.
   - After pruning, run `pytest tests/ -v` again and `cd frontend && npm run build` to confirm nothing broke.
   - If removing an API endpoint, also check for external consumers (Dispatcharr callbacks, webhook URLs, cron jobs calling the API).
   - **Never prune comments that explain WHY something works a certain way** — only remove commented-out dead code.
   - When in doubt, leave it and mark with `# TODO: PRUNE? — verify with user` instead of removing.

**Evaluation principles (apply these when deciding if code is dead or pruneable):**
- **"Zero callers" is necessary but not sufficient.** Also ask: does removing it lose any capability? If another endpoint/function covers the same functionality, it's safe. If it's the only way to do something, be cautious even if nothing calls it today.
- **Duplicate endpoints:** When GET and POST versions exist doing the same thing, the POST (superset — accepts optional body) is the keeper. The GET adds no unique capability.
- **Consider external consumers** that won't show up in code search: browser bookmarks, monitoring scripts, curl commands, Dispatcharr callbacks, Docker healthchecks, cron jobs. GET endpoints are especially exposed since they're URL-accessible.
- **Frontend has two calling patterns:** structured api clients (`frontend/src/api/*.ts`) and direct `fetch()` calls in pages/components. Always search the ENTIRE `frontend/src/` for URL path strings.
- **Never trust automated dead-code detection without manual verification.** The Q1 2026 audit had a high false-positive rate because agents only searched api client files, missing direct `fetch()` calls.
- **"Is it called?" is the wrong question. "Would we lose capability?" is the right one.**

**Ongoing responsibilities (during normal development):**
- When you encounter dead code while working on features/bugs, mark it with `# TODO: PRUNE — <reason>` immediately.
- When you notice layer violations or code smell, add `# TODO: REFACTOR — <reason>`.
- These TODO markers get cleaned up during the next audit cycle.
- After each audit, update these evaluation principles with any new lessons learned.
- Create the next child bead (e.g., `Code Health Audit — Mar 2026`) when closing the current one.

**Audit epic details:** `bd show teamarrv2-5hq`

## Sync Status

When asked to **"sync status"** or **"update status"**:

1. Query GitHub issues: `gh issue list --state all --limit 50`
2. Query GitHub PRs: `gh pr list --state all --limit 20`
3. Read PR/issue comments for context: `gh api repos/Pharaoh-Labs/teamarr/issues/<id>/comments`
4. Query beads: `bd list`, `bd list --label roadmap`
5. Cross-reference issues ↔ beads (check which issues have epics, which don't)
6. Update `plans/STATUS.md` with:
   - Open issues table (with bead mapping)
   - Open PRs table (with status/notes)
   - Roadmap epics (ready vs blocked)
   - Issues needing beads
   - Recently closed items
   - Change log entry with date
7. Present summary and recommend next steps

## Adding a New League

Add to `INSERT OR REPLACE INTO leagues` in `teamarr/database/schema.sql`. Restart to apply.

## Database Schema Changes

**Adding a new column:** Just add it to the `CREATE TABLE` in `schema.sql`. Schema reconciliation (`teamarr/database/reconciliation.py`) automatically detects and adds missing columns on startup by comparing the real database against an in-memory reference built from `schema.sql`. No migration block needed.

**Data migration (transforming existing data):** Add a versioned `if current_version < N:` block in `_run_migrations()` in `connection.py`. Bump the `schema_version DEFAULT` in `schema.sql`. Column additions in mixed blocks should use `_add_column_if_not_exists` as a safety net for tests that call `_run_migrations` directly.

**Table rebuild (CHECK constraint changes):** Add a pre-migration function in `init_db()` that backs up the table, drops it, and lets `executescript` recreate it. Add a restore block in `_run_migrations` keyed on the backup table's existence. See `_migrate_settings_for_v65` as the pattern.

**Startup order:** `init_db` → verify integrity → structural pre-migrations → reconcile schema → executescript → data migrations → seed cache.

## Common Commands

```bash
source .venv/bin/activate
python3 app.py                    # Run on port 9195
pytest tests/ -v                  # Run tests
ruff check teamarr/               # Lint
ruff format teamarr/              # Format
cd frontend && npm run build      # Build frontend
```

## Logging

**Configuration:** `teamarr/utilities/logging.py`

**Log directory detection** (in priority order):
1. `LOG_DIR` env var (if set)
2. `/app/data/logs` (if `/app/data` exists - Docker or host with `/app`)
3. `<project_root>/logs` (local dev fallback)

**IMPORTANT:** On this dev machine, `/app/data/` exists at the system level, so both Docker AND local dev write to `/app/data/logs/` (not `./data/logs/`).

**Log files:**
| File | Contents |
|------|----------|
| `teamarr.log` | Main log (rotating 10MB x 5) |
| `teamarr_errors.log` | Errors only (rotating 10MB x 3) |

**View recent logs:**
```bash
tail -n 100 /app/data/logs/teamarr.log      # On this dev machine
tail -n 100 ./data/logs/teamarr.log         # Standard Docker setup
docker logs --tail 100 teamarr              # Docker container stdout
```

**Environment variables** (set in docker-compose.yml):
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR (default: INFO for console, DEBUG for files)
- `LOG_FORMAT`: "text" or "json" (default: text)
- `LOG_DIR`: Override log directory path

**Note:** `./data/logs/` in the project directory contains stale V1 logs from Dec 2025 - these can be deleted.

## MCP Servers

**Playwright** (`@playwright/mcp`) - Browser automation for testing UI, capturing screenshots, verifying frontend changes. Tools available:
- `browser_navigate` - Navigate to URL
- `browser_click` - Click elements
- `browser_type` - Enter text in fields
- `browser_snapshot` - Get accessibility tree (preferred over screenshots)
- `browser_screenshot` - Capture page screenshot

Use for: Visual verification of UI changes, testing frontend flows, debugging styling issues.

