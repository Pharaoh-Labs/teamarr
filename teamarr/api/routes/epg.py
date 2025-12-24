"""EPG generation endpoints."""

import json
import logging
import queue
import threading
from datetime import date, datetime

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

from teamarr.api.dependencies import get_sports_service
from teamarr.api.generation_status import (
    complete_generation,
    fail_generation,
    get_status,
    is_in_progress,
    start_generation,
    update_status,
)
from teamarr.api.models import (
    EPGGenerateRequest,
    EPGGenerateResponse,
    EventEPGRequest,
    MatchStats,
    StreamBatchMatchRequest,
    StreamBatchMatchResponse,
    StreamMatchResultModel,
)
from teamarr.consumers import CachedMatcher  # Complex component with DB integration
from teamarr.database import get_db
from teamarr.services import (
    EventEPGOptions,
    SportsDataService,
    TeamChannelConfig,
    TeamEPGOptions,
    create_epg_service,
)

router = APIRouter()


# =============================================================================
# Team-based EPG endpoints
# =============================================================================


def _load_team_configs(team_ids: list[int] | None = None) -> list[TeamChannelConfig]:
    """Load team configs with their templates from database."""
    with get_db() as conn:
        # Join teams with templates to get template fields
        query = """
            SELECT t.*,
                   tpl.title_format,
                   tpl.subtitle_template as subtitle_format,
                   tpl.xmltv_categories
            FROM teams t
            LEFT JOIN templates tpl ON t.template_id = tpl.id
            WHERE t.active = 1
        """
        if team_ids:
            placeholders = ",".join("?" * len(team_ids))
            query = f"""
                SELECT t.*,
                       tpl.title_format,
                       tpl.subtitle_template as subtitle_format,
                       tpl.xmltv_categories
                FROM teams t
                LEFT JOIN templates tpl ON t.template_id = tpl.id
                WHERE t.id IN ({placeholders}) AND t.active = 1
            """
            cursor = conn.execute(query, team_ids)
        else:
            cursor = conn.execute(query)

        configs = []
        for row in cursor.fetchall():
            # Parse category from JSON array if present
            category = None
            if row["xmltv_categories"]:
                import json

                cats = json.loads(row["xmltv_categories"])
                if cats:
                    category = cats[0]  # Use first category

            configs.append(
                TeamChannelConfig(
                    team_id=row["provider_team_id"],
                    league=row["primary_league"],
                    team_name=row["team_name"],
                    team_abbrev=row["team_abbrev"],
                    channel_id=row["channel_id"],
                    logo_url=row["channel_logo_url"] or row["team_logo_url"],
                    title_format=row["title_format"],
                    subtitle_format=row["subtitle_format"],
                    category=category,
                    template_id=row["template_id"],
                )
            )
        return configs


def _parse_team_ids(team_ids: str | None) -> list[int] | None:
    """Parse comma-separated team IDs."""
    if not team_ids:
        return None
    try:
        return [int(x.strip()) for x in team_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_ids must be comma-separated integers",
        ) from None


def _get_settings() -> dict:
    """Load settings from database."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if row:
            settings = dict(row)
        else:
            # Fallback defaults
            settings = {
                "team_schedule_days_ahead": 30,  # For .next vars, conditionals
                "event_match_days_ahead": 3,
                "epg_output_days_ahead": 14,  # Days in XMLTV output
                "epg_lookback_hours": 6,
                "duration_default": 3.0,
                "duration_basketball": 3.0,
                "duration_football": 3.5,
                "duration_hockey": 3.0,
                "duration_baseball": 3.5,
                "duration_soccer": 2.5,
                "duration_rugby": 2.5,
                "duration_boxing": 4.0,
                "duration_tennis": 3.0,
                "duration_golf": 6.0,
                "duration_racing": 3.0,
                "duration_cricket": 4.0,
            }

        # Build sport_durations dict from duration_* fields
        settings["sport_durations"] = {
            "basketball": settings.get("duration_basketball", 3.0),
            "football": settings.get("duration_football", 3.5),
            "hockey": settings.get("duration_hockey", 3.0),
            "baseball": settings.get("duration_baseball", 3.5),
            "soccer": settings.get("duration_soccer", 2.5),
            "rugby": settings.get("duration_rugby", 2.5),
            "boxing": settings.get("duration_boxing", 4.0),
            "tennis": settings.get("duration_tennis", 3.0),
            "golf": settings.get("duration_golf", 6.0),
            "racing": settings.get("duration_racing", 3.0),
            "cricket": settings.get("duration_cricket", 4.0),
        }
        settings["default_duration"] = settings.get("duration_default", 3.0)

        return settings


@router.post("/epg/generate", response_model=EPGGenerateResponse)
def generate_epg(
    request: EPGGenerateRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Generate full EPG using the unified generation workflow.

    This endpoint calls run_full_generation() which handles:
    - M3U refresh
    - Team and event group processing
    - XMLTV generation and file output
    - Dispatcharr integration
    - Channel lifecycle (deletions, reconciliation, cleanup)

    For real-time progress, use GET /epg/generate/stream instead.
    """
    from teamarr.consumers.generation import run_full_generation
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client

    # Get Dispatcharr client if configured
    with get_db() as conn:
        dispatcharr_settings = get_dispatcharr_settings(conn)

    dispatcharr_client = None
    if dispatcharr_settings.enabled and dispatcharr_settings.url:
        dispatcharr_client = get_dispatcharr_client(get_db)

    # Run unified generation
    result = run_full_generation(
        db_factory=get_db,
        dispatcharr_client=dispatcharr_client,
        progress_callback=None,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Generation failed",
        )

    return EPGGenerateResponse(
        programmes_count=result.programmes_total,
        teams_processed=result.teams_processed,
        events_processed=result.groups_programmes,
        duration_seconds=result.duration_seconds,
        run_id=result.run_id,
        match_stats=MatchStats(
            streams_fetched=0,
            streams_filtered=0,
            streams_eligible=0,
            streams_matched=0,
            streams_unmatched=0,
            streams_cached=0,
            match_rate=0.0,
        ),
    )


@router.get("/epg/generate/status")
def get_generation_status():
    """Get current EPG generation status for polling-based progress.

    Returns JSON with:
    - in_progress: bool - whether generation is running
    - status: str - current status (starting, progress, complete, error, idle)
    - message: str - human-readable message
    - percent: int - progress percentage (0-100)
    - phase: str - current phase (teams, groups, saving)
    - current: int - current item number
    - total: int - total items in current phase
    - item_name: str - name of current item being processed
    """
    return get_status()


@router.get("/epg/generate/stream")
def generate_epg_stream():
    """Stream EPG generation progress using Server-Sent Events.

    This endpoint calls the unified run_full_generation() function which
    handles the complete EPG workflow including:
    - M3U refresh
    - Team and event group processing
    - XMLTV generation and file output
    - Dispatcharr integration (EPG refresh, channel association)
    - Channel lifecycle (scheduled deletions)
    - Reconciliation (detect issues)
    - History cleanup
    """
    from teamarr.consumers.generation import run_full_generation
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client

    # Check if already in progress
    if is_in_progress():
        return StreamingResponse(
            iter([f"data: {json.dumps({'status': 'error', 'message': 'Generation already in progress'})}\n\n"]),
            media_type="text/event-stream",
        )

    # Mark as started
    if not start_generation():
        return StreamingResponse(
            iter([f"data: {json.dumps({'status': 'error', 'message': 'Failed to start generation'})}\n\n"]),
            media_type="text/event-stream",
        )

    # Queue for progress updates
    progress_queue: queue.Queue = queue.Queue()

    def generate():
        """Generator function for SSE stream."""

        def run_generation():
            """Run EPG generation in background thread."""
            try:
                # Get Dispatcharr client if configured
                with get_db() as conn:
                    dispatcharr_settings = get_dispatcharr_settings(conn)

                dispatcharr_client = None
                if dispatcharr_settings.enabled and dispatcharr_settings.url:
                    dispatcharr_client = get_dispatcharr_client(get_db)

                # Progress callback that updates status and queues for SSE
                def progress_callback(phase: str, percent: int, message: str, current: int, total: int, item_name: str):
                    update_status(
                        status="progress",
                        phase=phase,
                        percent=percent,
                        message=message,
                        current=current,
                        total=total,
                        item_name=item_name,
                    )
                    progress_queue.put(get_status())

                # Run unified generation
                result = run_full_generation(
                    db_factory=get_db,
                    dispatcharr_client=dispatcharr_client,
                    progress_callback=progress_callback,
                )

                if result.success:
                    complete_generation({
                        "success": True,
                        "programmes_count": result.programmes_total,
                        "teams_processed": result.teams_processed,
                        "groups_processed": result.groups_processed,
                        "duration_seconds": result.duration_seconds,
                        "run_id": result.run_id,
                    })
                else:
                    fail_generation(result.error or "Unknown error")

                progress_queue.put(get_status())

            except Exception as e:
                fail_generation(str(e))
                progress_queue.put(get_status())

            finally:
                progress_queue.put({"_done": True})

        # Start generation thread
        generation_thread = threading.Thread(target=run_generation, daemon=True)
        generation_thread.start()

        # Stream progress updates
        while True:
            try:
                data = progress_queue.get(timeout=0.5)

                if data.get("_done"):
                    break

                yield f"data: {json.dumps(data)}\n\n"

            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"

        # Wait for thread to complete
        generation_thread.join(timeout=5)

        # Send final status
        yield f"data: {json.dumps(get_status())}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/epg/xmltv")
def get_xmltv(
    team_ids: str | None = Query(None, description="Comma-separated team IDs"),
    days_ahead: int | None = Query(None, ge=1, le=90, description="Days ahead"),
    service: SportsDataService = Depends(get_sports_service),
):
    """Get XMLTV output for team-based EPG."""
    parsed_ids = _parse_team_ids(team_ids)
    epg_service = create_epg_service(service)
    configs = _load_team_configs(parsed_ids)

    if not configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active teams found",
        )

    # Use settings defaults
    settings = _get_settings()
    schedule_days = settings["team_schedule_days_ahead"]
    output_days = days_ahead if days_ahead is not None else settings["epg_output_days_ahead"]

    options = TeamEPGOptions(
        schedule_days_ahead=schedule_days,
        output_days_ahead=output_days,
        sport_durations=settings["sport_durations"],
        default_duration_hours=settings["default_duration"],
    )
    result = epg_service.generate_team_epg(configs, options)

    return Response(
        content=result.xmltv,
        media_type="application/xml",
        headers={"Content-Disposition": "inline; filename=teamarr.xml"},
    )


# =============================================================================
# Event-based EPG endpoints
# =============================================================================


def _parse_date(date_str: str | None) -> date:
    """Parse date string or return today."""
    if not date_str:
        return date.today()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        ) from None


@router.post("/epg/events/generate", response_model=EPGGenerateResponse)
def generate_event_epg(
    request: EventEPGRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Generate event-based EPG. Each event gets its own channel."""
    epg_service = create_epg_service(service)
    target = _parse_date(request.target_date)

    options = EventEPGOptions(
        pregame_minutes=request.pregame_minutes,
    )

    result = epg_service.generate_event_epg(
        request.leagues, target, request.channel_prefix, options
    )

    return EPGGenerateResponse(
        programmes_count=len(result.programmes),
        teams_processed=0,
        events_processed=result.events_processed,
        duration_seconds=(result.completed_at - result.started_at).total_seconds(),
    )


@router.get("/epg/events/xmltv")
def get_event_xmltv(
    leagues: str = Query(..., description="Comma-separated league codes"),
    target_date: str | None = Query(None, description="Date (YYYY-MM-DD)"),
    channel_prefix: str = Query("event"),
    pregame_minutes: int = Query(30, ge=0, le=120),
    duration_hours: float = Query(3.0, ge=1.0, le=8.0),
    service: SportsDataService = Depends(get_sports_service),
):
    """Get XMLTV for event-based EPG. Each event gets its own channel."""
    league_list = [x.strip() for x in leagues.split(",") if x.strip()]
    if not league_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one league required",
        )

    epg_service = create_epg_service(service)
    target = _parse_date(target_date)

    options = EventEPGOptions(
        pregame_minutes=pregame_minutes,
    )

    result = epg_service.generate_event_epg(league_list, target, channel_prefix, options)

    return Response(
        content=result.xmltv,
        media_type="application/xml",
        headers={"Content-Disposition": "inline; filename=teamarr-events.xml"},
    )


# =============================================================================
# Stream Matching (with fingerprint cache)
# =============================================================================


@router.post("/epg/streams/match", response_model=StreamBatchMatchResponse)
def match_streams(
    request: StreamBatchMatchRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Match streams to events using fingerprint cache.

    On cache hit: returns cached event, skips expensive matching.
    On cache miss: performs full match, caches result.

    Fingerprint = hash(group_id + stream_id + stream_name).
    If stream name changes, fingerprint changes -> fresh match.
    """
    target = _parse_date(request.target_date)

    # Create cached matcher for this group
    matcher = CachedMatcher(
        service=service,
        get_connection=get_db,
        search_leagues=request.search_leagues,
        group_id=request.group_id,
        include_leagues=request.include_leagues,
    )

    # Convert input to dicts
    streams = [{"id": s.id, "name": s.name} for s in request.streams]

    # Match all streams (uses cache where possible)
    batch_result = matcher.match_all(streams, target)

    # Purge stale cache entries
    matcher.purge_stale()

    # Build response
    results = []
    for r in batch_result.results:
        result_model = StreamMatchResultModel(
            stream_name=r.stream_name,
            matched=r.matched,
            event_id=r.event.id if r.event else None,
            event_name=r.event.name if r.event else None,
            league=r.league,
            home_team=r.event.home_team.name if r.event else None,
            away_team=r.event.away_team.name if r.event else None,
            start_time=r.event.start_time.isoformat() if r.event else None,
            included=r.included,
            exclusion_reason=r.exclusion_reason,
            from_cache=getattr(r, "from_cache", False),
        )
        results.append(result_model)

    return StreamBatchMatchResponse(
        total=batch_result.total,
        matched=batch_result.matched_count,
        included=batch_result.included_count,
        unmatched=batch_result.unmatched_count,
        match_rate=batch_result.match_rate,
        cache_hits=batch_result.cache_hits,
        cache_misses=batch_result.cache_misses,
        cache_hit_rate=batch_result.cache_hit_rate,
        results=results,
    )


# =============================================================================
# EPG Analysis
# =============================================================================


def _get_combined_xmltv() -> str:
    """Get combined XMLTV content from all teams."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT xmltv_content FROM team_epg_xmltv ORDER BY team_id"
        ).fetchall()

    if not rows:
        return ""

    # Merge all XMLTV content
    from teamarr.utilities.xmltv import merge_xmltv_content

    contents = [row["xmltv_content"] for row in rows if row["xmltv_content"]]
    if not contents:
        return ""

    return merge_xmltv_content(contents)


def _analyze_xmltv(xmltv_content: str) -> dict:
    """Analyze XMLTV content for issues."""
    import re
    import xml.etree.ElementTree as ET
    from collections import defaultdict

    result = {
        "channels": {"total": 0, "team_based": 0, "event_based": 0},
        "programmes": {
            "total": 0,
            "events": 0,
            "pregame": 0,
            "postgame": 0,
            "idle": 0,
        },
        "date_range": {"start": None, "end": None},
        "unreplaced_variables": [],
        "coverage_gaps": [],
    }

    if not xmltv_content:
        return result

    try:
        # Parse with comments
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(xmltv_content, parser=parser)
    except ET.ParseError:
        return result

    # Count channels
    channels = root.findall("channel")
    result["channels"]["total"] = len(channels)
    for ch in channels:
        ch_id = ch.get("id", "")
        if ch_id.startswith("teamarr-event-"):
            result["channels"]["event_based"] += 1
        else:
            result["channels"]["team_based"] += 1

    # Analyze programmes
    programmes = root.findall("programme")
    result["programmes"]["total"] = len(programmes)

    # Track programmes per channel for gap detection
    channel_programmes: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    unreplaced_vars: set[str] = set()
    var_pattern = re.compile(r"\{[a-z_]+\}")

    min_start = None
    max_stop = None

    for prog in programmes:
        channel_id = prog.get("channel", "")
        start = prog.get("start", "")
        stop = prog.get("stop", "")

        # Track date range
        if start:
            start_date = start[:8]
            if min_start is None or start_date < min_start:
                min_start = start_date
        if stop:
            stop_date = stop[:8]
            if max_stop is None or stop_date > max_stop:
                max_stop = stop_date

        # Get text content for variable checking
        title = prog.findtext("title", "") or ""
        subtitle = prog.findtext("sub-title", "") or ""
        desc = prog.findtext("desc", "") or ""

        # Check for programme type from filler comment (V1 compatibility)
        # Comments look like: <!-- teamarr:filler-pregame -->
        filler_type = None
        for child in prog:
            if callable(child.tag):  # This is a Comment
                comment_text = child.text or ""
                if comment_text.startswith("teamarr:filler-"):
                    filler_type = comment_text.replace("teamarr:filler-", "")
                    break

        if filler_type == "pregame":
            result["programmes"]["pregame"] += 1
        elif filler_type == "postgame":
            result["programmes"]["postgame"] += 1
        elif filler_type == "idle":
            result["programmes"]["idle"] += 1
        else:
            result["programmes"]["events"] += 1

        for text in [title, subtitle, desc]:
            if text:
                matches = var_pattern.findall(text)
                unreplaced_vars.update(matches)

        # Store for gap detection
        if channel_id and start and stop:
            channel_programmes[channel_id].append((start, stop, title or "Unknown"))

    result["unreplaced_variables"] = sorted(unreplaced_vars)
    result["date_range"]["start"] = min_start
    result["date_range"]["end"] = max_stop

    # Detect coverage gaps (> 5 minute gap between programmes)
    from datetime import datetime

    for channel_id, progs in channel_programmes.items():
        # Sort by start time
        progs.sort(key=lambda x: x[0])

        for i in range(len(progs) - 1):
            _, stop1, title1 = progs[i]
            start2, _, title2 = progs[i + 1]

            # Parse times (format: YYYYMMDDHHmmss +ZZZZ)
            try:
                stop1_time = stop1[:14]
                start2_time = start2[:14]

                fmt = "%Y%m%d%H%M%S"
                dt_stop = datetime.strptime(stop1_time, fmt)
                dt_start = datetime.strptime(start2_time, fmt)

                gap_seconds = (dt_start - dt_stop).total_seconds()
                gap_minutes = int(gap_seconds / 60)

                if gap_minutes > 5:  # More than 5 minute gap
                    result["coverage_gaps"].append(
                        {
                            "channel": channel_id,
                            "after_program": title1[:50],
                            "before_program": title2[:50],
                            "after_stop": stop1,
                            "before_start": start2,
                            "gap_minutes": gap_minutes,
                        }
                    )
            except (ValueError, TypeError):
                continue

    return result


@router.get("/epg/analysis")
def get_epg_analysis():
    """Analyze current EPG for issues.

    Returns:
    - Channel counts (team vs event based)
    - Programme counts by type (events, pregame, postgame, idle) from latest run
    - Date range coverage
    - Unreplaced template variables
    - Coverage gaps between programmes
    """
    xmltv = _get_combined_xmltv()
    result = _analyze_xmltv(xmltv)

    # Override programme counts with stats from latest processing run
    # (XML comments may not survive serialization, so use DB stats instead)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT programmes_total, programmes_events, programmes_pregame,
                   programmes_postgame, programmes_idle
            FROM processing_runs
            WHERE status = 'completed'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            result["programmes"]["total"] = row["programmes_total"] or result["programmes"]["total"]
            result["programmes"]["events"] = row["programmes_events"] or 0
            result["programmes"]["pregame"] = row["programmes_pregame"] or 0
            result["programmes"]["postgame"] = row["programmes_postgame"] or 0
            result["programmes"]["idle"] = row["programmes_idle"] or 0

    return result


@router.get("/epg/content")
def get_epg_content(
    max_lines: int = Query(2000, ge=100, le=10000, description="Max lines to return"),
):
    """Get raw XMLTV content for preview.

    Returns the combined XMLTV content as text for display in UI.
    """
    xmltv = _get_combined_xmltv()

    if not xmltv:
        return {"content": "", "total_lines": 0, "truncated": False}

    lines = xmltv.split("\n")
    total_lines = len(lines)
    truncated = total_lines > max_lines

    if truncated:
        lines = lines[:max_lines]

    return {
        "content": "\n".join(lines),
        "total_lines": total_lines,
        "truncated": truncated,
        "size_bytes": len(xmltv.encode("utf-8")),
    }


# =============================================================================
# Match stats endpoints
# =============================================================================


@router.get("/epg/matched-streams")
def get_matched_streams(
    run_id: int | None = Query(None, description="Processing run ID (defaults to latest)"),
    group_id: int | None = Query(None, description="Filter by event group ID"),
    limit: int = Query(500, ge=1, le=2000, description="Max results"),
):
    """Get matched streams from an EPG generation run.

    Returns list of streams that were successfully matched to events.
    """
    from teamarr.database.stats import get_matched_streams as db_get_matched

    with get_db() as conn:
        streams = db_get_matched(conn, run_id=run_id, group_id=group_id, limit=limit)

    return {
        "count": len(streams),
        "run_id": run_id,
        "group_id": group_id,
        "streams": streams,
    }


@router.get("/epg/failed-matches")
def get_failed_matches(
    run_id: int | None = Query(None, description="Processing run ID (defaults to latest)"),
    group_id: int | None = Query(None, description="Filter by event group ID"),
    reason: str | None = Query(None, description="Filter by failure reason"),
    limit: int = Query(500, ge=1, le=2000, description="Max results"),
):
    """Get failed matches from an EPG generation run.

    Returns list of streams that failed to match to events.

    Reasons:
    - unmatched: No event found for stream
    - excluded_league: Matched but event is in non-configured league
    - exception: Stream contains exception keyword
    """
    from teamarr.database.stats import get_failed_matches as db_get_failed

    with get_db() as conn:
        failures = db_get_failed(
            conn, run_id=run_id, group_id=group_id, reason=reason, limit=limit
        )

    return {
        "count": len(failures),
        "run_id": run_id,
        "group_id": group_id,
        "reason_filter": reason,
        "failures": failures,
    }


@router.get("/epg/match-stats")
def get_match_stats(
    run_id: int | None = Query(None, description="Processing run ID (defaults to latest)"),
):
    """Get match statistics summary for an EPG generation run.

    Returns:
    - Total matched/unmatched/cached counts
    - Match rate percentage
    - Breakdown by group and league
    - Failure reasons breakdown
    """
    from teamarr.database.stats import get_match_stats_summary

    with get_db() as conn:
        stats = get_match_stats_summary(conn, run_id=run_id)

    return stats
