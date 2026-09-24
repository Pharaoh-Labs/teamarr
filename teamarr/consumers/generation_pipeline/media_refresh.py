"""Detached media refresh work for the generation pipeline."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from teamarr.channelsdvr.client import ChannelsDVRClient
from teamarr.emby.client import EmbyClient
from teamarr.jellyfin.client import JellyfinClient

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
    )

    try:
        with db_factory() as conn:
            emby_settings = get_emby_settings(conn)
            jellyfin_settings = get_jellyfin_settings(conn)
            channelsdvr_settings = get_channelsdvr_settings(conn)
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
    return {"emby": "Emby", "jellyfin": "Jellyfin", "channelsdvr": "Channels DVR"}.get(
        kind, "media server"
    )


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
    return True


def run_media_server_refreshes(
    jobs: list[tuple[str, Any]],
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
    completion_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str, dict]]:
    """Run every media-server refresh job concurrently (#471).

    Each job is (kind, server) with kind in emby/jellyfin/channelsdvr.
    Returns (kind, label, outcome) triples where outcome carries "guide"
    (Emby/Jellyfin) or "m3u"/"epg" (Channels DVR) result dicts. A job that
    raises yields a failed "guide" outcome — never an exception.
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


def refresh_one_media_server(
    kind: str,
    server: Any,
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
) -> dict:
    """Refresh a single media server (runs on a worker thread)."""
    label = server.name or server.url or ""

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
