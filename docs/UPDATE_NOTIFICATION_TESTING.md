# Update Notification Testing Guide

This guide explains how to test and simulate the update notification feature for both stable and dev builds.

## Overview

The update notification system checks for updates from two sources:
- **Stable releases**: GitHub Releases API (`https://api.github.com/repos/{owner}/{repo}/releases/latest`)
- **Dev builds**: GitHub Container Registry (`https://ghcr.io/v2/{owner}/{image}/manifests/{tag}`)

## Configuration

Update check settings can be configured via the API or database:

### Default Settings

```json
{
  "enabled": true,
  "check_interval_hours": 24,
  "notify_stable_updates": true,
  "notify_dev_updates": false,
  "github_owner": "Pharaoh-Labs",
  "github_repo": "teamarr",
  "ghcr_owner": "pharaoh-labs",
  "ghcr_image": "teamarr",
  "dev_tag": "dev"
}
```

### Update Settings via API

```bash
curl -X PATCH http://localhost:9195/api/v1/updates/settings \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "check_interval_hours": 6,
    "github_owner": "YourOrg",
    "github_repo": "your-fork",
    "ghcr_owner": "yourorg",
    "ghcr_image": "your-image",
    "dev_tag": "nightly"
  }'
```

## Testing Scenarios

### 1. Test Stable Release Checking

Stable builds are versions without branch suffixes (e.g., `2.0.11`, not `2.0.11-dev+abc123`).

#### Simulate a Stable Build

To test stable update checking, you need to run a version that looks like a stable release:

```bash
# Method 1: Temporarily modify version in pyproject.toml
# Change version from "2.0.11" to an older version like "2.0.9"
# Then restart the app

# Method 2: Set environment variable (requires code change to support)
export TEAMARR_VERSION="2.0.9"
```

#### Check for Updates

```bash
# Get current update status
curl -s http://localhost:9195/api/v1/updates/status | jq

# Force a fresh check (bypass cache)
curl -s "http://localhost:9195/api/v1/updates/status?force=true" | jq
```

#### Expected Response (Update Available)

```json
{
  "current_version": "2.0.9",
  "latest_version": "2.0.11",
  "update_available": true,
  "build_type": "stable",
  "download_url": "https://github.com/Pharaoh-Labs/teamarr/releases/tag/v2.0.11",
  "release_notes_url": "https://github.com/Pharaoh-Labs/teamarr/releases/tag/v2.0.11",
  "checked_at": "2026-01-26T16:45:00",
  "settings": { ... }
}
```

#### Expected Response (No Update)

```json
{
  "current_version": "2.0.11",
  "latest_version": "2.0.11",
  "update_available": false,
  "build_type": "stable",
  "download_url": "https://github.com/Pharaoh-Labs/teamarr/releases/tag/v2.0.11",
  "release_notes_url": "https://github.com/Pharaoh-Labs/teamarr/releases/tag/v2.0.11",
  "checked_at": "2026-01-26T16:45:00",
  "settings": { ... }
}
```

### 2. Test Dev Build Checking

Dev builds have branch names in the version (e.g., `2.0.11-dev+abc123`, `2.0.11-feature-xyz+def456`).

The current implementation automatically detects dev builds by checking for `-` and `+` in the version string.

#### Simulate a Dev Build

Dev builds are automatically detected when running from a branch:

```bash
# Running from a feature branch automatically creates a dev version:
# Example: "2.0.11-copilot/feature-name+abc123"

# Check the current version
curl -s http://localhost:9195/health | jq .version
```

#### Check for Updates (Dev)

```bash
# Get current update status
curl -s http://localhost:9195/api/v1/updates/status | jq

# Expected to check GHCR instead of GitHub Releases
```

#### Expected Response (Dev Build)

```json
{
  "current_version": "2.0.11-dev+abc123",
  "latest_version": "dev (sha256:12345)",
  "update_available": false,
  "build_type": "dev",
  "download_url": "https://ghcr.io/pharaoh-labs/teamarr:dev",
  "release_notes_url": null,
  "checked_at": "2026-01-26T16:45:00",
  "settings": { ... }
}
```

**Note**: Dev update checking requires authentication to GHCR for private registries. The current implementation may return `update_available: false` conservatively if it cannot verify the manifest.

### 3. Test with Custom Repository (Forks)

If you're running a fork of Teamarr, you can configure it to check your own repositories:

```bash
# Configure to check your fork
curl -X PATCH http://localhost:9195/api/v1/updates/settings \
  -H "Content-Type: application/json" \
  -d '{
    "github_owner": "YourUsername",
    "github_repo": "teamarr",
    "ghcr_owner": "yourusername",
    "ghcr_image": "teamarr",
    "dev_tag": "main"
  }'

# Check for updates from your fork
curl -s "http://localhost:9195/api/v1/updates/status?force=true" | jq
```

### 4. Test Health Endpoint Integration

The health endpoint includes update information when enabled:

```bash
# Check health endpoint
curl -s http://localhost:9195/health | jq

# Expected response includes update info:
{
  "status": "healthy",
  "version": "2.0.11",
  "startup": { ... },
  "update": {
    "update_available": false,
    "latest_version": "2.0.11",
    "build_type": "stable",
    "checked_at": "2026-01-26T16:45:00"
  }
}
```

### 5. Test Caching Behavior

The update checker caches results to avoid excessive API calls:

```bash
# First check - hits the API
curl -s "http://localhost:9195/api/v1/updates/status?force=true" | jq .checked_at

# Second check - uses cache (same timestamp)
curl -s http://localhost:9195/api/v1/updates/status | jq .checked_at

# Force fresh check - new timestamp
curl -s "http://localhost:9195/api/v1/updates/status?force=true" | jq .checked_at
```

Cache duration is controlled by `check_interval_hours` setting (default: 24 hours).

### 6. Test Disabled State

```bash
# Disable update checking
curl -X PATCH http://localhost:9195/api/v1/updates/settings \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Verify it returns disabled state
curl -s http://localhost:9195/api/v1/updates/status | jq
# Expected: checked_at will be null, no API calls made
```

## Version Detection Logic

The system automatically determines build type from the version string:

| Version Format | Build Type | Update Source |
|----------------|------------|---------------|
| `2.0.11` | stable | GitHub Releases |
| `2.0.11-dev+abc123` | dev | GHCR (ghcr.io) |
| `2.0.11-feature+abc123` | dev | GHCR (ghcr.io) |
| `2.0.11-main+abc123` | dev | GHCR (ghcr.io) |

## Environment-Based Testing

### Testing Stable Releases

```bash
# Edit pyproject.toml to set version to an older release
# For example, change from 2.0.11 to 2.0.10
vim pyproject.toml

# Restart the application
# The version will now be "2.0.10" and it will check against GitHub Releases
```

### Testing Dev Builds

```bash
# Create a feature branch (this automatically creates a dev version)
git checkout -b test-feature

# The version will be like "2.0.11-test-feature+abc123"
# It will check against GHCR

# Configure to check a specific dev tag
curl -X PATCH http://localhost:9195/api/v1/updates/settings \
  -H "Content-Type: application/json" \
  -d '{"dev_tag": "nightly"}'
```

## API Endpoints

### GET `/api/v1/updates/status`

Get current update status.

**Query Parameters:**
- `force` (boolean): Force a fresh check, bypassing cache

**Response:** UpdateStatusResponse with current version, latest version, and settings

### PATCH `/api/v1/updates/settings`

Update the update check settings.

**Request Body:**
```json
{
  "enabled": true,
  "check_interval_hours": 24,
  "notify_stable_updates": true,
  "notify_dev_updates": false,
  "github_owner": "Pharaoh-Labs",
  "github_repo": "teamarr",
  "ghcr_owner": "pharaoh-labs",
  "ghcr_image": "teamarr",
  "dev_tag": "dev"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Update check settings updated"
}
```

### GET `/health`

Health endpoint includes update information when available.

## Troubleshooting

### No Updates Detected

1. **Check cache**: Use `force=true` to bypass cache
2. **Check settings**: Ensure `enabled: true`
3. **Verify version format**: Use `/health` to see current version
4. **Check logs**: Look for `[UPDATE_CHECKER]` messages

### GHCR Authentication Errors (Dev Builds)

Dev build checking against GHCR may fail with 401 errors for private registries:

```
WARNING | [UPDATE_CHECKER] Failed to check for updates: Client error '401 Unauthorized'
```

**Solution**: For public images, this is expected to work without auth. For private images, you would need to implement token-based authentication (not currently supported).

### Rate Limiting

GitHub API has rate limits:
- **Unauthenticated**: 60 requests/hour
- **Authenticated**: 5,000 requests/hour (not implemented)

The caching mechanism helps avoid hitting these limits.

## Manual Testing Script

Here's a complete test script:

```bash
#!/bin/bash

BASE_URL="http://localhost:9195"

echo "=== Testing Update Notification System ==="
echo ""

echo "1. Check current version and status:"
curl -s "$BASE_URL/health" | jq '{version, update}'
echo ""

echo "2. Get update status (cached):"
curl -s "$BASE_URL/api/v1/updates/status" | jq '{current_version, latest_version, update_available, build_type, checked_at}'
echo ""

echo "3. Force fresh update check:"
curl -s "$BASE_URL/api/v1/updates/status?force=true" | jq '{current_version, latest_version, update_available, build_type, checked_at}'
echo ""

echo "4. View current settings:"
curl -s "$BASE_URL/api/v1/updates/status" | jq .settings
echo ""

echo "5. Test disabling updates:"
curl -s -X PATCH "$BASE_URL/api/v1/updates/settings" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' | jq
curl -s "$BASE_URL/api/v1/updates/status" | jq .checked_at
echo ""

echo "6. Re-enable updates:"
curl -s -X PATCH "$BASE_URL/api/v1/updates/settings" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' | jq
echo ""

echo "=== Tests Complete ==="
```

Save as `test_updates.sh`, make executable with `chmod +x test_updates.sh`, and run with `./test_updates.sh`.
