---
title: Troubleshooting
parent: User Guide
nav_order: 11
docs_version: "2.3.1"
---

# Troubleshooting

Common issues and how to resolve them.

## Stream Matching

### Streams show as "Failed" after generation

Failed streams couldn't be matched to a real sporting event. Common causes:

- **Stream name too vague** — Names like "Sports 1" or "NBA 3" don't contain team names. Teamarr needs identifiable team or event information.
- **League not subscribed** — The stream's league isn't enabled in Event Groups > Global Defaults. Enable it and regenerate.
- **Team name mismatch** — Your IPTV provider uses a non-standard name. Add a [team alias](detection-library#team-aliases) to map it to the official name.
- **Date mismatch** — Streams with dates in DD/MM format may be parsed as MM/DD. Use [custom regex extractors](event-groups/creating-groups#custom-regex-extractors) with named groups (`(?P<day>...)/(?P<month>...)`) to fix this.

Click the **Failed** count in the run history to see details for each unmatched stream. Use the **Fix** button to manually match a stream to an event.

### Streams matching the wrong event

- Check the [Detection Library](detection-library) for conflicting league or sport hints
- Verify your stream filters (include/exclude regex) aren't too broad
- Use the preview button on the Event Groups page to see matches without running a full generation

## Channels

### Channels not appearing in Headendarr or Dispatcharr

1. Verify your integration is connected (Settings > Headendarr or Settings > Dispatcharr shows "Connected")
2. Verify the target platform has Teamarr's XMLTV source configured or provisioned
3. Run EPG generation and check if streams matched successfully
4. Check [channel lifecycle timing](settings/channels#channel-lifecycle) — channels may not be created yet based on your create timing settings

### Channels disappearing unexpectedly

- Check [delete timing](settings/channels#channel-lifecycle) — channels are deleted based on post-event buffer settings
- Review the [Recently Deleted](channels#recently-deleted) section on the Channels page
- If using "Same day" delete timing, channels are removed at midnight

### Channel numbers colliding with existing channels

Set the **Channel Range Start** in Settings > Channels to a range that doesn't overlap with your existing Headendarr or Dispatcharr channels. For example, if you have channels 1-500, set the start to 1000.

### Stale logos in media server

Some media servers (particularly Jellyfin) cache channel logos aggressively. Enable **Scheduled Channel Reset** in Settings > EPG to periodically purge and recreate channels before your media server's guide refresh.

## Headendarr or Dispatcharr Connection

### "Connection error" when testing

- Verify the URL includes the protocol (`http://` or `https://`)
- Check that Headendarr or Dispatcharr is running and accessible at the specified port
- If using Docker, ensure both containers are on the same network or use the correct IP/hostname
- Check for firewalls blocking the port

### EPG source dropdown is empty

- In Dispatcharr, add Teamarr's XMLTV URL as an EPG source first. Copy the URL from the EPG page in Teamarr and add it in Dispatcharr's EPG sources.
- In Headendarr, make sure the Teamarr host is configured in Settings > Headendarr, then use the provisioning action so Teamarr can create or refresh the `Teamarr` XMLTV source automatically.

## Generation

### Generation takes too long

- Reduce **Event Lookahead** in Settings > Event Groups (shorter window = fewer events to check)
- Reduce **Schedule Days Ahead** in Settings > Teams (fewer days = less schedule data)
- Use per-group subscription overrides to limit which leagues each group scans
- Ensure the team/league cache is fresh (Settings > System > Refresh Cache)

### Generation fails or shows errors

Check the logs for details:

```bash
# Docker
docker logs --tail 200 teamarr

# Log file (inside container or data volume)
tail -n 200 data/logs/teamarr.log
```

Common causes:
- Network timeout reaching ESPN or TSDB APIs
- Headendarr or Dispatcharr API returning errors (check the target platform logs too)
- Database locked (shouldn't happen in normal operation — restart if it does)

## Database & Upgrades

### Startup crash after upgrade

If Teamarr fails to start after pulling a new image, check the logs for migration errors. Common fixes:

- **Never delete `teamarr.db`** — it contains all your configuration. Migrations handle schema changes automatically.
- If upgrading from a very old version (pre-2.1.2), the migration path should work automatically. If it doesn't, file a bug report with the error message.

### Restoring a backup

Go to Settings > System > Backup & Restore. Upload a `.db` backup file. A backup of your current database is created automatically before restoring. The application needs to be restarted after restore.

## Logs

Teamarr writes to two log files in the `data/logs/` directory:

| File | Contents | Rotation |
|------|----------|----------|
| `teamarr.log` | All log messages (DEBUG and above) | 10 MB x 5 files |
| `teamarr_errors.log` | Errors only | 10 MB x 3 files |

The console log level is controlled by the `LOG_LEVEL` environment variable (default: `INFO`). File logs always capture `DEBUG` regardless of this setting.

```bash
# View recent logs
docker logs --tail 100 teamarr          # Console output
docker exec teamarr cat data/logs/teamarr.log | tail -100  # Log file
```

## Getting Help

- **GitHub Issues**: [github.com/Pharaoh-Labs/teamarr/issues](https://github.com/Pharaoh-Labs/teamarr/issues)
- **Discord**: Join the Teamarr or platform community Discord that you use for deployment support
