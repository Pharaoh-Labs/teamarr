"""Detached media refresh work for the generation pipeline."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from teamarr.channelsdvr.client import ChannelsDVRClient
from teamarr.emby.client import EmbyClient
from teamarr.jellyfin.client import JellyfinClient
from teamarr.plex.client import (
    PlexClient,
    compute_channelmap_update,
    device_read_problem,
    guide_path_from_lineup,
    is_complete_xmltv,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

logger = logging.getLogger("teamarr.consumers.generation")
_media_refresh_lock = threading.Lock()


def stage_media_jobs(
    context: GenerationContext,
    get_jobs: Callable[[Callable[[], Any]], list[tuple[str, Any]]],
    dry_run_refresh: Callable[[Any, list[tuple[str, Any]]], bool],
) -> None:
    """Snapshot refresh jobs and suppress them under DRY_RUN."""
    context.media_jobs = get_jobs(context.db_factory)
    if context.media_jobs and dry_run_refresh(context.result, context.media_jobs):
        context.media_jobs = []


def get_media_refresh_jobs(db_factory: Callable[[], Any]) -> list[tuple[str, Any]]:
    """Snapshot enabled media servers for the post-generation refresh batch."""
    from teamarr.database.settings import (
        get_channelsdvr_settings,
        get_emby_settings,
        get_jellyfin_settings,
        get_plex_settings,
    )

    try:
        with db_factory() as conn:
            emby_settings = get_emby_settings(conn)
            jellyfin_settings = get_jellyfin_settings(conn)
            channelsdvr_settings = get_channelsdvr_settings(conn)
            plex_settings = get_plex_settings(conn)
    except Exception as exc:
        logger.warning("[MEDIA_SERVERS] Could not load refresh settings: %s", exc)
        return []

    jobs: list[tuple[str, Any]] = []
    if emby_settings.enabled:
        jobs.extend(("emby", server) for server in emby_settings.servers if server.url)
    if jellyfin_settings.enabled:
        jobs.extend(("jellyfin", server) for server in jellyfin_settings.servers if server.url)
    if channelsdvr_settings.enabled:
        jobs.extend(
            ("channelsdvr", server) for server in channelsdvr_settings.servers if server.url
        )
    if plex_settings.enabled:
        jobs.extend(("plex", server) for server in plex_settings.servers if server.url)
    return jobs


def start_media_server_refresh(
    db_factory: Callable[[], Any], run_id: int, jobs: list[tuple[str, Any]]
) -> None:
    """Run a guide refresh batch after generation completion.

    Batches wait for one another so a server never receives overlapping guide
    refreshes, but this worker never blocks the next generation's core work.
    """

    def run() -> None:
        with _media_refresh_lock:
            started_at = time.time()
            try:
                from teamarr.consumers.media_refresh_status import (
                    complete_refresh,
                    start_refresh,
                    update_refresh,
                )

                start_refresh(len(jobs))
                outcomes = run_media_server_refreshes(
                    jobs,
                    lambda phase, _percent, _message, *_: update_refresh(
                        f"Refreshing {media_refresh_title(phase)} guide..."
                    ),
                    lambda: False,
                    db_factory,
                    lambda current, _total: update_refresh("Refreshing media servers...", current),
                )
                flattened = [
                    media_server_outcome(kind, label, outcome) for kind, label, outcome in outcomes
                ]
                complete_refresh(flattened)
            except Exception as exc:  # noqa: BLE001 - detached worker must not escape
                logger.exception("[MEDIA_SERVERS] Background refresh failed")
                from teamarr.consumers.media_refresh_status import fail_refresh

                fail_refresh(str(exc))
                flattened = [
                    {
                        "kind": kind,
                        "server": getattr(server, "name", None) or getattr(server, "url", ""),
                        "success": False,
                        "duration": 0.0,
                        "error": str(exc),
                    }
                    for kind, server in jobs
                ]

            save_media_refresh_outcomes(
                db_factory, run_id, flattened, round(time.time() - started_at, 2)
            )

    threading.Thread(target=run, daemon=True, name=f"media-refresh-{run_id}").start()


def media_refresh_title(kind: str) -> str:
    """Return a user-facing integration name without exposing server details."""
    return {
        "emby": "Emby",
        "jellyfin": "Jellyfin",
        "channelsdvr": "Channels DVR",
        "plex": "Plex",
    }.get(kind, "media server")


def save_media_refresh_outcomes(
    db_factory: Callable[[], Any], run_id: int, outcomes: list[dict], duration: float
) -> None:
    """Attach detached refresh outcomes to the EPG run that scheduled them."""
    from teamarr.database.stats import get_run, save_run

    try:
        with db_factory() as conn:
            run = get_run(conn, run_id)
            if run is None:
                logger.warning(
                    "[MEDIA_SERVERS] Run %d disappeared before refresh completed", run_id
                )
                return
            run.extra_metrics["media_servers"] = outcomes
            run.extra_metrics.setdefault("phase_timings", {})["media_server_refresh"] = duration
            save_run(conn, run)
    except Exception as exc:  # noqa: BLE001 - guide refresh must never affect generation
        logger.exception("[MEDIA_SERVERS] Could not save background refresh outcomes: %s", exc)


def dry_run_media_refresh(result: Any, jobs: list[tuple[str, Any]]) -> bool:
    """DRY_RUN (#554): record what would have been refreshed, run nothing.

    Returns True when dry-run is active (caller skips the refresh jobs).
    """
    from teamarr.config.runtime import dry_run

    if not dry_run():
        return False
    by_kind: dict[str, list[str]] = {}
    for kind, server in jobs:
        by_kind.setdefault(kind, []).append(getattr(server, "url", None) or str(server))
    for kind, urls in by_kind.items():
        logger.info("[DRY_RUN] Suppressed %s guide refresh for %s", kind, ", ".join(urls))
        payload = {"success": True, "dry_run": True, "servers": urls}
        result.media_server_outcomes += [
            {
                "kind": kind,
                "server": u,
                "success": True,
                "duration": 0.0,
                "error": None,
                "dry_run": True,
            }
            for u in urls
        ]
        if kind == "emby":
            result.emby_refresh = payload
        elif kind == "jellyfin":
            result.jellyfin_refresh = payload
        elif kind == "channelsdvr":
            result.channelsdvr_refresh = payload
            result.channelsdvr_epg_refresh = dict(payload)
        elif kind == "plex":
            result.plex_refresh = payload
    return True


def run_media_server_refreshes(
    jobs: list[tuple[str, Any]],
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
    db_factory: Callable[[], Any],
    completion_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str, dict]]:
    """Run every media-server refresh job concurrently (#471).

    Each job is (kind, server) with kind in emby/jellyfin/channelsdvr/plex.
    Returns (kind, label, outcome) triples where outcome carries "guide"
    (Emby/Jellyfin/Plex) or "m3u"/"epg" (Channels DVR) result dicts. A job
    that raises yields a failed "guide" outcome — never an exception.
    Plex needs `db_factory`: it reads the managed-channel set and its own
    pushed-channel record on the worker thread.
    """

    results: list[tuple[str, str, dict]] = []
    with ThreadPoolExecutor(
        max_workers=min(8, len(jobs)), thread_name_prefix="media-refresh"
    ) as pool:
        futures = {
            pool.submit(
                refresh_one_media_server,
                kind,
                server,
                update_progress,
                is_cancellation_requested,
                db_factory,
            ): (kind, server)
            for kind, server in jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            kind, server = futures[future]
            label = server.name or server.url or ""
            try:
                results.append((kind, label, future.result()))
            except Exception as e:  # noqa: BLE001 — per-server isolation
                logger.warning(
                    "[%s] %s: refresh failed (non-blocking): %s",
                    kind.upper(),
                    label,
                    e,
                )
                results.append((kind, label, {"guide": {"success": False, "error": str(e)}}))
            if completion_callback:
                completion_callback(completed, len(jobs))
    return results


def media_server_outcome(kind: str, label: str, outcome: dict) -> dict:
    """Flatten one server's refresh result for the run row (#649).

    Channels DVR has two steps (m3u + epg); it counts as a success only when
    both did, and reports the first error.
    """
    parts = [v for v in (outcome.get("guide"), outcome.get("m3u"), outcome.get("epg")) if v]
    errors = [p.get("error") or p.get("message") for p in parts if not p.get("success")]
    return {
        "kind": kind,
        "server": label,
        "success": bool(parts) and all(p.get("success") for p in parts),
        "duration": round(sum(float(p.get("duration") or 0) for p in parts), 2),
        "error": errors[0] if errors else None,
    }


_PLEX_GUIDE_READY_TIMEOUT_SECONDS = 90
_PLEX_GUIDE_READY_POLL_SECONDS = 3


def _wait_for_dispatcharr_guide(
    lineup: str | None,
    db_factory: Callable[[], Any],
    label: str,
    is_cancellation_requested: Callable[[], bool],
) -> dict | None:
    """Hold until the XMLTV guide Plex is about to fetch is complete.

    The channelmap PUT makes Plex fetch the DVR's guide from Dispatcharr right
    away. If Dispatcharr is still rewriting it (channel/EPG updates just ran),
    Plex reads a truncated document and can crash outright (2026-09-20: libxml
    "Extra content at the end of the document", then SIGFPE). Returns None when
    the guide parses whole; otherwise a failure dict, so the PUT is skipped and
    the next generation run retries — Plex is never pointed at a bad guide.

    When the guide URL can't be derived or Dispatcharr isn't configured there
    is nothing to check, so the PUT proceeds as before.
    """
    import httpx

    from teamarr.database.settings import get_dispatcharr_settings

    path = guide_path_from_lineup(lineup)
    with db_factory() as conn:
        base = (get_dispatcharr_settings(conn).url or "").rstrip("/")
    if not path or not base:
        return None

    url = f"{base}{path}"
    deadline = time.monotonic() + _PLEX_GUIDE_READY_TIMEOUT_SECONDS
    while True:
        if is_cancellation_requested():
            return {"success": False, "error": "Cancelled"}
        try:
            resp = httpx.get(url, timeout=30)
            if resp.status_code == 200 and is_complete_xmltv(resp.content):
                return None
            detail = f"HTTP {resp.status_code}" if resp.status_code != 200 else "incomplete XMLTV"
        except httpx.HTTPError as e:
            detail = str(e)
        if time.monotonic() >= deadline:
            logger.warning(
                "[PLEX] %s: Dispatcharr guide not ready after %ds (%s) — skipping channel "
                "map update this run",
                label,
                _PLEX_GUIDE_READY_TIMEOUT_SECONDS,
                detail,
            )
            return {"success": False, "error": f"Dispatcharr guide not ready: {detail}"}
        time.sleep(_PLEX_GUIDE_READY_POLL_SECONDS)


def _channel_in_profile(raw_profile_ids: str | None, profile_id: int | str) -> bool:
    """Check a managed_channels row's ``channel_profile_ids`` against one profile.

    Mirrors the read-back parsing in ``reconciliation.py`` (JSON TEXT column,
    empty/invalid -> no profiles). ``0`` is Dispatcharr's ALL-profiles
    sentinel (see ``creator.py``'s ``[0]`` default) and always matches.
    """
    if not raw_profile_ids:
        return False
    try:
        ids = json.loads(raw_profile_ids)
    except (TypeError, ValueError):
        return False
    if not isinstance(ids, list):
        return False
    return 0 in ids or profile_id in ids or str(profile_id) in {str(i) for i in ids}


def _plex_desired_channels(
    conn: Any, profile_id: int | str | None, label: str
) -> set[str]:
    """Channel numbers Teamarr currently manages for this device's scope.

    Covers BOTH event channels (``managed_channels``) and managed team
    channels: team channels default to 9000+ and were invisible here, so the
    old range-based ownership claimed them without ever listing them and
    disabled them on every run.

    The two tables carry profile scope differently. An event channel stores
    its own ``channel_profile_ids``; a team channel has no such column (and
    no ``deleted_at``) — its profiles come from the global
    ``managed_team_channel_profile_ids`` setting, and it is live when its
    team is still managed and it has a Dispatcharr channel.
    """
    if profile_id is None:
        logger.warning(
            "[PLEX] %s: no Dispatcharr channel profile selected — managing every "
            "Teamarr channel on this device regardless of profile scope",
            label,
        )

    keys: set[str] = set()

    for row in conn.execute(
        """SELECT channel_number, channel_profile_ids FROM managed_channels
           WHERE deleted_at IS NULL AND channel_number IS NOT NULL"""
    ).fetchall():
        if profile_id is not None and not _channel_in_profile(
            row["channel_profile_ids"], profile_id
        ):
            continue
        try:
            keys.add(str(int(float(row["channel_number"]))))
        except (TypeError, ValueError):
            continue

    if not _team_channels_in_profile(conn, profile_id):
        return keys

    for row in conn.execute(
        """SELECT mtc.channel_number
           FROM managed_team_channels mtc
           JOIN teams t ON t.id = mtc.team_id
           WHERE t.managed_channel_enabled = 1
             AND mtc.dispatcharr_channel_id IS NOT NULL
             AND mtc.channel_number IS NOT NULL"""
    ).fetchall():
        try:
            keys.add(str(int(float(row["channel_number"]))))
        except (TypeError, ValueError):
            continue

    return keys


def _team_channels_in_profile(conn: Any, profile_id: int | str | None) -> bool:
    """Whether managed team channels belong to this device's profile.

    Team channels have no per-row profile; they all land in the profiles named
    by the global ``managed_team_channel_profile_ids`` setting. ``None`` there
    means every profile.
    """
    if profile_id is None:
        return True
    try:
        from teamarr.database.settings import get_dispatcharr_settings

        configured = get_dispatcharr_settings(conn).managed_team_channel_profile_ids
    except Exception:  # noqa: BLE001 — scoping must never break the refresh
        return True
    if configured is None:
        return True
    wanted = str(profile_id)
    return any(
        str(item) == wanted or str(item) == "0"
        for item in configured
        if not (isinstance(item, str) and "{" in item)
    ) or any(isinstance(item, str) and "{" in item for item in configured)


def _find_plex_device(dvrs: list[Any], device_key: str) -> tuple[Any, Any] | None:
    return next(
        ((dvr, d) for dvr in dvrs for d in dvr.devices if d.key == device_key),
        None,
    )


def refresh_plex_server(
    server: Any,
    label: str,
    db_factory: Callable[[], Any],
    progress: Callable[[str], None],
    is_cancellation_requested: Callable[[], bool],
) -> dict:
    """Push Teamarr's current channels into the device's channelmap.

    The channelmap PUT is the only call needed (2026-09-12 live testing):
    it's what Plex's own UI sends when you open a tuner's Channel Matching
    screen and hit Save with no changes, and doing so triggers a full guide
    refresh on its own. The separate ``reloadGuide`` endpoint does not
    reliably refresh programme data and is not used.

    Ownership is recorded, never inferred from a channel-number range (see
    ``teamarr.database.plex_state``). The computed set is a union of what the
    device already has enabled and what Teamarr manages, so a channel Teamarr
    does not own cannot be disabled at any number.

    Order matters: the Dispatcharr guide wait happens BEFORE the device read,
    so the state the write is based on is as fresh as possible. Plex fetches
    the guide the moment the channelmap lands, and has been seen crashing on
    a half-written one (2026-09-20).

    Callers only filter on `server.url` (matching Emby/Jellyfin/Channels DVR);
    a missing dvr_id/device_key is reported here as a visible failure rather
    than silently dropped from the job list.
    """
    from teamarr.database.plex_state import get_pushed_channels, set_pushed_channels

    if not server.token:
        return {"success": False, "error": "No Plex token configured"}
    if not server.dvr_id or not server.device_key:
        return {"success": False, "error": "No DVR/device selected in Settings"}

    def cancelled() -> dict | None:
        if is_cancellation_requested():
            return {"success": False, "error": "Cancelled"}
        return None

    def fail(message: str) -> dict:
        logger.warning("[PLEX] %s: %s", label, message)
        return {"success": False, "error": message}

    client = PlexClient(base_url=server.url, token=server.token or "")
    profile_id = server.channel_profile_id

    if result := cancelled():
        return result

    # The lineup URL lives on the DVR, so one read is needed before the guide
    # wait; the authoritative read for the write happens after it.
    probe = client.list_dvrs()
    if not probe.get("success"):
        return fail(f"could not read DVR/device state: {probe.get('error')}")
    found = _find_plex_device(probe["dvrs"], server.device_key)
    if found is None:
        return fail(f"configured device {server.device_key} no longer found on server")

    progress("Waiting for Dispatcharr guide...")
    if not_ready := _wait_for_dispatcharr_guide(
        found[0].lineup, db_factory, label, is_cancellation_requested
    ):
        return not_ready

    if result := cancelled():
        return result

    # Re-read immediately before the write — the guide wait can take a while.
    dvrs_result = client.list_dvrs()
    if not dvrs_result.get("success"):
        return fail(f"could not read DVR/device state: {dvrs_result.get('error')}")
    found = _find_plex_device(dvrs_result["dvrs"], server.device_key)
    if found is None:
        return fail(f"configured device {server.device_key} no longer found on server")
    _, device = found

    with db_factory() as conn:
        desired = _plex_desired_channels(conn, profile_id, label)
        previously_pushed = get_pushed_channels(
            conn, server.url, server.device_key, profile_id
        )

    if problem := device_read_problem(device, expect_channels=bool(previously_pushed)):
        return fail(f"refusing to write: {problem}")

    enabled, mapping = compute_channelmap_update(
        device.channel_mapping, desired, previously_pushed
    )

    carried = {m.device_identifier for m in device.channel_mapping}
    if not_carried := desired - carried:
        logger.warning(
            "[PLEX] %s: %d managed channel(s) are not on this device's tuner "
            "(e.g. %s) — check the Dispatcharr channel profile for this device",
            label,
            len(not_carried),
            sorted(not_carried)[:5],
        )

    currently_enabled = {m.device_identifier for m in device.channel_mapping if m.enabled}
    if not enabled and currently_enabled:
        return fail(
            "refusing to write: computed an empty channel set while the device "
            f"has {len(currently_enabled)} enabled"
        )
    if losing := (currently_enabled - set(enabled)) - previously_pushed:
        return fail(
            "refusing to write: would disable "
            f"{len(losing)} channel(s) Teamarr never pushed ({sorted(losing)[:5]})"
        )

    if result := cancelled():
        return result

    progress("Updating Plex channel map...")
    map_result = client.update_channelmap(device.key, enabled, mapping)
    if not map_result.get("success"):
        return fail(f"channel map update failed: {map_result.get('error')}")

    # A 200 does not mean Plex applied anything — a request it ignores still
    # answers 200 (live-tested 2026-10-07). Confirm against a fresh read.
    verify = client.list_dvrs()
    if verify.get("success"):
        found = _find_plex_device(verify["dvrs"], server.device_key)
        if found is not None:
            live = {m.device_identifier for m in found[1].channel_mapping if m.enabled}
            # Only channels the tuner actually carries can be enabled, so a
            # managed channel outside this device's lineup is not evidence the
            # write was ignored.
            if missing := (set(enabled) & carried) - live:
                return fail(
                    f"channel map write was not applied ({len(missing)} channel(s) "
                    f"still not enabled, e.g. {sorted(missing)[:5]})"
                )
    else:
        logger.warning(
            "[PLEX] %s: could not verify channel map write: %s", label, verify.get("error")
        )

    with db_factory() as conn:
        set_pushed_channels(conn, server.url, server.device_key, profile_id, desired)

    logger.info(
        "[PLEX] %s: channel map updated (%d channels enabled, %d Teamarr-managed)",
        label,
        len(enabled),
        len(desired),
    )
    return map_result


def refresh_one_media_server(
    kind: str,
    server: Any,
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
    db_factory: Callable[[], Any],
) -> dict:
    """Refresh a single media server (runs on a worker thread)."""
    label = server.name or server.url or ""

    if kind == "plex":
        return {
            "guide": refresh_plex_server(
                server,
                label,
                db_factory,
                lambda msg: update_progress("plex", 97, f"{msg} ({label})"),
                is_cancellation_requested,
            )
        }

    if kind == "channelsdvr":
        m3u_res, epg_res = refresh_channelsdvr_server(
            server,
            label,
            lambda msg: update_progress("channelsdvr", 97, f"{msg} ({label})"),
        )
        return {"m3u": m3u_res, "epg": epg_res}

    title = "Emby" if kind == "emby" else "Jellyfin"
    client_cls = EmbyClient if kind == "emby" else JellyfinClient
    client = client_cls(
        base_url=server.url,
        username=server.username or "",
        password=server.password or "",
        api_key=server.api_key,
    )

    update_progress(kind, 97, f"Refreshing {title} guide... ({label})")

    def on_progress(pct):
        update_progress(kind, 97, f"Refreshing {title} guide... ({label}) {pct:.0f}%")

    guide_result = client.trigger_guide_refresh(
        timeout=300,
        on_progress=on_progress,
        cancellation_check=is_cancellation_requested,
    )
    if guide_result.get("success"):
        logger.info(
            "[%s] %s: guide refresh completed in %.1fs",
            kind.upper(),
            label,
            guide_result.get("duration", 0),
        )
    else:
        logger.warning(
            "[%s] %s: guide refresh failed: %s",
            kind.upper(),
            label,
            guide_result.get("message"),
        )
    return {"guide": guide_result}


def refresh_channelsdvr_server(
    server: Any,
    label: str,
    progress: Callable[[str], None],
) -> tuple[dict | None, dict | None]:
    """Refresh one Channels DVR server's M3U source, then its XMLTV lineup.

    Sequences the two refreshes on real evidence: waits for the M3U
    channel-list refresh to actually finish before firing the guide PUT,
    so the guide doesn't index against a stale channel list. Both waits
    poll CDVR /log (see client docs).

    Returns (m3u_result, epg_result); either is None when that phase
    didn't run (no source / no lineup configured).
    """
    # The client derives lineup_id as "XMLTV-<source_name>" when no lineup
    # is explicitly configured, so the guide refresh fires even if the
    # user only set the M3U source.
    client = ChannelsDVRClient(
        base_url=server.url,
        source_name=server.source_name or "",
        lineup_id=server.lineup_id or "",
    )

    if not (client.source_name or client.lineup_id):
        logger.warning(
            "[CHANNELSDVR] %s: enabled but no source name or XMLTV lineup "
            "configured — nothing to refresh. Set a source name "
            "(and optionally a lineup) in Settings.",
            label,
        )
        return None, None

    m3u_result: dict | None = None
    if client.source_name:
        progress("Refreshing Channels DVR channels...")
        m3u_result = client.trigger_m3u_refresh(
            timeout=60, wait_for_completion=bool(client.lineup_id)
        )
        if m3u_result.get("success"):
            logger.info(
                "[CHANNELSDVR] %s: M3U refresh triggered in %.1fs (completion: %s)",
                label,
                m3u_result.get("duration", 0),
                m3u_result.get("completed", "not awaited"),
            )
        else:
            logger.warning(
                "[CHANNELSDVR] %s: M3U refresh failed: %s",
                label,
                m3u_result.get("message"),
            )

    epg_result: dict | None = None
    if client.lineup_id:
        if client.lineup_derived:
            logger.info(
                "[CHANNELSDVR] %s: no XMLTV lineup configured; derived '%s' from source '%s'",
                label,
                client.lineup_id,
                client.source_name,
            )
        progress("Refreshing Channels DVR guide...")
        epg_result = client.trigger_epg_refresh(timeout=60, verify=True)
        if not epg_result.get("success"):
            logger.warning(
                "[CHANNELSDVR] %s: EPG refresh failed: %s",
                label,
                epg_result.get("message"),
            )
        else:
            verification = epg_result.get("verification") or {}
            status = verification.get("status")
            if status == "no_fetch":
                logger.warning(
                    "[CHANNELSDVR] %s: EPG refresh accepted but guide '%s' "
                    "was not re-fetched — guide may be stale",
                    label,
                    client.lineup_id,
                )
            else:
                logger.info(
                    "[CHANNELSDVR] %s: EPG refresh for lineup '%s' in %.1fs (verification: %s)",
                    label,
                    client.lineup_id,
                    epg_result.get("duration", 0),
                    status or "not verified",
                )
    else:
        logger.warning(
            "[CHANNELSDVR] %s: skipping EPG/guide refresh: no XMLTV lineup "
            "configured and none could be derived (set a source name so the "
            "lineup can be inferred). The guide will stay stale until "
            "refreshed manually.",
            label,
        )

    return m3u_result, epg_result
