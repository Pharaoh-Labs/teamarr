# Test Suite Map

~1,320 tests organized by subject directory (bead `teamarrv2-iua3.5`). Run
everything with `pytest tests/ -q` — the full suite finishes in under 10s.

## Layout

| Directory | What it protects |
|-----------|------------------|
| `matching/` | Stream → event matching: classifiers, fuzzy/team/racing matchers, match cache, name-match gating, team filters |
| `epg/` | EPG program matching (Dispatcharr program guide), EPG resolver/index, XMLTV output and filler categories |
| `lifecycle/` | Managed-channel create/sync/delete, Dispatcharr sync reliability, numbering, cleanup, stream stats |
| `providers/` | Provider clients (shared BaseHTTPClient, ESPN, TSDB, NASCAR, Supabase), sports-data service layer, call telemetry |
| `templates/` | Template engine: variables, scope gating, resolution priority, validation, sample/preview system |
| `migrations/` | Schema upgrades: versioned migrations, checkpoint_v43, reconciliation, migration conventions (static analysis) |
| `subscriptions/` | Global sports subscription, per-group overrides, unsubscribed-league cleanup, sub-scheduler |
| `integrations/` | External clients: Dispatcharr auth/stats, Channels DVR, Jellyfin/Emby, settings API parity |

Big cross-cutting behavior files stay top-level: `test_custom_leagues.py`,
`test_tennis.py`, `test_feed_separation.py`, `test_stream_ordering.py`,
`test_team_import_collisions.py`.

## Shared infrastructure

- **`conftest.py`** — `db_path` / `db_factory` / `db_conn` fixtures: a
  temp-file database initialized through the full startup path (init_db →
  migrations → reconciliation). Use these instead of per-file tmp-DB
  boilerplate.
- **`fakes.py`** — shared duck-typed fakes (`FakeEvent`, `FakeGroup`,
  `FakeChannel`, `FakeManagedChannel`, ...) and the `make_event` factory.
  Each is the field-union of what tests need; add fields rather than
  re-declaring a local fake.
- **`helpers.py`** — `REPO_ROOT` / `SCHEMA_PATH` constants. Never compute
  repo paths from a test file's `__file__` (breaks when files move).

## Conventions

- New test files go in the matching subject directory; only genuinely
  cross-cutting suites stay top-level.
- Version-pinned migration tests (`*_v59`, `*_v73`, ...) live in
  `migrations/` and are candidates for merging into consolidated
  per-concern files (iua3.5 steps 4–5).
- Before consolidating files, prove no case loss:
  `pytest tests/ --co -q | tail -1` must match before and after.
