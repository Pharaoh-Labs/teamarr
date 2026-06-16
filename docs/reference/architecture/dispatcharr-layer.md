---
title: Dispatcharr Integration Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 4
docs_version: "2.3.1"
---

# Dispatcharr Integration Layer

The `teamarr/dispatcharr/` package provides a typed, thread-safe client for Dispatcharr's REST API. It handles authentication, retry logic, connection management, and domain-specific operations through specialized managers.

## Architecture

```
DispatcharrFactory (singleton)
        │
        ▼
DispatcharrConnection
  ├── DispatcharrClient  (HTTP + auth + retry)
  ├── ChannelManager     (channel CRUD, O(1) cache)
  ├── EPGManager         (EPG refresh + polling)
  ├── M3UManager         (streams + groups)
  └── LogoManager        (upload + dedup)
```

## Client (`client.py`)

Low-level HTTP client with JWT authentication and exponential backoff retry.

| Setting | Value |
|---------|-------|
| Timeout | 30 seconds |
| Max retries | 5 |
| Backoff | `min(32s, 1s × 2^attempt) × jitter(0.5-1.5)` |
| Retryable codes | 502, 503, 504 |
| Non-retryable | 401, 403, 404, other 4xx |

On 401 responses, the client clears the JWT token and retries once with fresh authentication.

**Key methods:** `get()`, `post()`, `patch()`, `delete()`, `paginated_get()`, `test_connection()`

## Authentication (`auth.py`)

`TokenManager` handles JWT token lifecycle:

- Session isolation by `{url}_{username}` key
- Proactive refresh 1 minute before expiry (5-minute token lifetime)
- Thread-safe with `threading.Lock`
- Fallback chain: cached token → refresh token → full auth

## Factory (`factory.py`)

`DispatcharrFactory` is a singleton that manages the connection lifecycle.

**Settings change detection:** Hash-based comparison of `{url}:{username}:{password}:{enabled}`. Auto-reconnects when settings change.

**Global convenience functions:**

| Function | Description |
|----------|-------------|
| `get_factory(db_factory)` | Get the singleton factory |
| `get_dispatcharr_client(db_factory)` | Get just the HTTP client |
| `get_dispatcharr_connection(db_factory)` | Get the full connection with managers |
| `test_dispatcharr_connection(...)` | Test with optional credential overrides |
| `close_dispatcharr()` | Close the active connection |

`ConnectionTestResult` returns: success, Dispatcharr version, account/group/channel counts, or error message.

## Data Types (`types.py`)

All response types are **frozen dataclasses** with `from_api(dict)` factory methods for safe deserialization.

### Channel Types

| Type | Key Fields |
|------|-----------|
| `DispatcharrChannel` | id, uuid, name, channel_number, tvg_id, channel_group_id, logo_id, logo_url, streams (tuple of IDs), stream_profile_id, channel_profile_ids |
| `DispatcharrStream` | id, name, url, channel_group, tvg_id, tvg_name, tvg_logo, m3u_account_id, is_stale |

### Infrastructure Types

| Type | Key Fields |
|------|-----------|
| `DispatcharrEPGSource` | id, name, source_type, url, status, last_message, updated_at |
| `DispatcharrProgram` | id, tvg_id, title, start_time, end_time, sub_title, description, epg_source, epg_name, epg_icon_url, stream_ids, channel_ids (+ `start_dt`/`end_dt`/`is_teamarr` helpers) |
| `DispatcharrM3UAccount` | id, name, status, url, updated_at |
| `DispatcharrChannelGroup` | id, name, m3u_accounts |
| `DispatcharrChannelProfile` | id, name, channel_ids |
| `DispatcharrStreamProfile` | id, name, command, is_active |
| `DispatcharrLogo` | id, name, url |

### Result Types

| Type | Key Fields | Usage |
|------|-----------|-------|
| `OperationResult` | success, message, error, data, channel, logo, duration | All CRUD operations |
| `RefreshResult` | success, message, duration, source, skipped, last_status | EPG/M3U refresh |
| `BatchRefreshResult` | success, results (per-account), failed/succeeded/skipped counts | Parallel M3U refresh |

## Channel Manager (`managers/channels.py`)

Channel CRUD with thread-safe O(1) caching for efficient lookups during generation.

**Cache indexes:** by ID, by tvg_id, by channel_number. Lazy population on first access, invalidated on mutations.

### Key Operations

| Method | Description |
|--------|-------------|
| `create_channel(...)` | Create with name, number, streams, tvg_id, group, profiles, logo |
| `update_channel(id, data)` | PATCH update with stream audit logging |
| `delete_channel(id)` | Delete with cache invalidation |
| `find_by_tvg_id(tvg_id)` | O(1) lookup |
| `find_by_number(number)` | O(1) lookup |
| `assign_streams(id, stream_ids)` | Replace stream list (order = priority) |

### Channel Profile Semantics

- `[]` — No profiles assigned
- `[0]` — All profiles (sentinel value)
- `[1, 2, ...]` — Specific profile IDs

### Stream Audit

On `update_channel`, the manager detects stream list mutations and logs differences between sent and API-returned stream lists. This catches stream loss bugs early.

## EPG Manager (`managers/epg.py`)

Async EPG refresh with polling for completion.

**Refresh flow:**
1. POST to trigger refresh → returns 202 (async queued)
2. Poll source status until `success`, `error`, or timeout
3. Special case: "no channels" message → instant success

**Cancellation support:** `wait_for_refresh()` accepts a `cancellation_check` callback, called before each poll iteration.

### Program-data search (EPG matching)

Supports matching streams to events by EPG program data (epic `teamarrv2-183`):

| Method | Description |
|--------|-------------|
| `supports_program_search(force=False)` | Feature-detection. Probes `GET /api/epg/programs/search/?page_size=1` once and caches: `200` → supported, `404` → unsupported (older Dispatcharr). Transient errors (no response / 5xx) are **not** cached so a later call retries. |
| `search_programs(tvg_id, start_before, end_after, title, channel_id, epg_source, page_size, fields)` | Returns `list[DispatcharrProgram]` across all pages via `paginated_get`. Short-circuits to `[]` when the endpoint is unsupported. Scope a day window with `start_before=<window end>`, `end_after=<window start>`. |

> **Version dependency.** The program-search endpoint (`/api/epg/programs/search/`) only exists on newer Dispatcharr builds — **confirmed working on Dispatcharr `0.24.0`**. Teamarr never hard-requires it: callers gate on `supports_program_search()` and degrade gracefully on older builds (EPG-based matching simply stays off). The settings toggle is feature-gated on this detection.

**Per-run index (`consumers/matching/epg_index.py`).** `EPGProgramIndex.build(...)` fetches programs **only** for the distinct `tvg_id`s of candidate streams in imported event groups (never the whole instance — one search call per `tvg_id`, since the endpoint takes a single `tvg_id` per call), excludes our own `_Teamarr` programs, and builds a `tvg_id → [programs]` index. `lookup(tvg_id, event_start, event_end)` returns programs whose time window overlaps the event (half-open). The matcher (`teamarrv2-183.4`) consumes this; the index itself holds no matching logic.

## M3U Manager (`managers/m3u.py`)

Stream discovery and M3U account management.

| Method | Description |
|--------|-------------|
| `list_streams(group_name, group_id, account_id)` | Filter streams by group/account |
| `refresh_account(account_id)` | Single account refresh |
| `refresh_multiple(account_ids)` | Parallel refresh with ThreadPoolExecutor |
| `wait_for_refresh(id, skip_if_recent_minutes)` | Skip if refreshed within threshold (default: 60 min) |

**UTF-8 fix:** Auto-detects and corrects double-encoded UTF-8 in stream names (common in some M3U sources where `ñ` becomes `Ã±`).

## Logo Manager (`managers/logos.py`)

Logo upload with URL-based deduplication.

| Method | Description |
|--------|-------------|
| `upload(name, url)` | Upload or return existing (by URL match) |
| `upload_or_find(name, url)` | Returns just the logo ID |
| `cleanup_unused()` | Delete logos not referenced by any channel |

## OperationResult Pattern

The core reliability pattern for Dispatcharr sync:

```
1. Call Dispatcharr API via manager method
2. Check OperationResult.success
3. If success → persist to local DB
4. If failure → leave DB unchanged → drift re-detected next run
```

This **closed-loop contract** means:
- No retry queue needed
- Self-healing on next generation run
- Profile sync additionally validates against Dispatcharr's actual state (not just DB expectations)

All channel updates in `ChannelLifecycleService` go through `_safe_update_channel()` which enforces this pattern.

## File Locations

| File | Purpose |
|------|---------|
| `dispatcharr/client.py` | HTTP client with retry |
| `dispatcharr/auth.py` | JWT token management |
| `dispatcharr/factory.py` | Connection factory (singleton) |
| `dispatcharr/types.py` | Frozen dataclasses for API responses |
| `dispatcharr/managers/channels.py` | Channel CRUD + cache |
| `dispatcharr/managers/epg.py` | EPG refresh + polling |
| `dispatcharr/managers/m3u.py` | M3U streams + groups |
| `dispatcharr/managers/logos.py` | Logo upload + dedup |
