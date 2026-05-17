"""External EPG sources management endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from teamarr.database.epg_sources import get_epg_sources_db, init_epg_sources_db
from teamarr.database.epg_sources import crud as epg_crud

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class EPGSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1)


class EPGSourceUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    url: str | None = None
    enabled: bool | None = None


class StreamMappingCreate(BaseModel):
    epg_channel_id: int
    dispatcharr_stream_id: int
    dispatcharr_stream_name: str | None = None
    m3u_account_id: int | None = None


class MappingToggle(BaseModel):
    enabled: bool


class ProgrammeSearch(BaseModel):
    pattern: str = Field(..., min_length=1)
    channel_id: int | None = None


# =============================================================================
# SOURCES
# =============================================================================


@router.get("/")
def list_sources(include_disabled: bool = Query(False)):
    init_epg_sources_db()
    with get_epg_sources_db() as conn:
        sources = epg_crud.list_sources(conn, include_disabled=include_disabled)
    return {"sources": sources}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_source(data: EPGSourceCreate):
    init_epg_sources_db()
    try:
        with get_epg_sources_db() as conn:
            source = epg_crud.create_source(conn, data.name, data.url)
        return source
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A source with this URL already exists",
            )
        raise


@router.get("/{source_id}")
def get_source(source_id: int):
    with get_epg_sources_db() as conn:
        source = epg_crud.get_source(conn, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}")
def update_source(source_id: int, data: EPGSourceUpdate):
    with get_epg_sources_db() as conn:
        existing = epg_crud.get_source(conn, source_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Source not found")

        update_data = data.model_dump(exclude_none=True)
        if not update_data:
            return existing

        source = epg_crud.update_source(conn, source_id, **update_data)
    return source


@router.delete("/{source_id}")
def delete_source(source_id: int):
    with get_epg_sources_db() as conn:
        deleted = epg_crud.delete_source(conn, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"success": True, "message": "Source deleted"}


@router.post("/{source_id}/refresh")
def refresh_source(source_id: int):
    """Fetch and re-parse XMLTV from source URL."""
    with get_epg_sources_db() as conn:
        source = epg_crud.get_source(conn, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    from teamarr.utilities.xmltv_parser import fetch_and_parse_source

    try:
        channels, programmes = fetch_and_parse_source(source["url"])
    except Exception as e:
        with get_epg_sources_db() as conn:
            epg_crud.update_source_fetch_status(conn, source_id, "error", str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch EPG source: {e}",
        )

    with get_epg_sources_db() as conn:
        epg_crud.upsert_channels(conn, source_id, channels)

        channel_rows = epg_crud.list_channels(conn, source_id)
        xmltv_to_db = {c["channel_xmltv_id"]: c["id"] for c in channel_rows}

        total_progs = 0
        for ch_xmltv_id, db_id in xmltv_to_db.items():
            ch_progs = [p for p in programmes if p["channel_xmltv_id"] == ch_xmltv_id]
            if ch_progs:
                epg_crud.replace_programmes(conn, db_id, ch_progs)
                total_progs += len(ch_progs)

        epg_crud.update_source_fetch_status(
            conn, source_id, "success",
            channel_count=len(channels),
            programme_count=total_progs,
        )

    return {
        "success": True,
        "channels": len(channels),
        "programmes": total_progs,
    }


# =============================================================================
# CHANNELS
# =============================================================================


@router.get("/{source_id}/channels")
def list_source_channels(source_id: int):
    with get_epg_sources_db() as conn:
        channels = epg_crud.list_channels(conn, source_id)
    return {"channels": channels}


@router.get("/channels/all")
def list_all_channels():
    init_epg_sources_db()
    with get_epg_sources_db() as conn:
        channels = epg_crud.list_channels(conn)
    return {"channels": channels}


# =============================================================================
# PROGRAMMES
# =============================================================================


@router.get("/channels/{channel_id}/programmes")
def list_programmes(
    channel_id: int,
    start_after: str | None = Query(None),
    end_before: str | None = Query(None),
    limit: int = Query(500, le=2000),
):
    with get_epg_sources_db() as conn:
        programmes = epg_crud.list_programmes(
            conn, channel_id,
            start_after=start_after,
            end_before=end_before,
            limit=limit,
        )
    return {"programmes": programmes}


@router.post("/programmes/search")
def search_programmes(data: ProgrammeSearch):
    with get_epg_sources_db() as conn:
        programmes = epg_crud.search_programmes(
            conn,
            title_pattern=data.pattern,
            channel_id=data.channel_id,
        )
    return {"programmes": programmes}


# =============================================================================
# STREAM MAPPINGS
# =============================================================================


@router.get("/mappings")
def list_mappings(enabled_only: bool = Query(True)):
    init_epg_sources_db()
    with get_epg_sources_db() as conn:
        mappings = epg_crud.list_mappings(conn, enabled_only=enabled_only)
    return {"mappings": mappings}


@router.post("/mappings", status_code=status.HTTP_201_CREATED)
def create_mapping(data: StreamMappingCreate):
    try:
        with get_epg_sources_db() as conn:
            mapping = epg_crud.create_mapping(
                conn,
                epg_channel_id=data.epg_channel_id,
                dispatcharr_stream_id=data.dispatcharr_stream_id,
                dispatcharr_stream_name=data.dispatcharr_stream_name,
                m3u_account_id=data.m3u_account_id,
            )
        return mapping
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This stream is already mapped",
            )
        raise


@router.delete("/mappings/{mapping_id}")
def delete_mapping(mapping_id: int):
    with get_epg_sources_db() as conn:
        deleted = epg_crud.delete_mapping(conn, mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"success": True, "message": "Mapping deleted"}


@router.patch("/mappings/{mapping_id}")
def toggle_mapping(mapping_id: int, data: MappingToggle):
    with get_epg_sources_db() as conn:
        mapping = epg_crud.toggle_mapping(conn, mapping_id, data.enabled)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return mapping


# =============================================================================
# DISPATCHARR STREAMS (for mapping UI)
# =============================================================================


@router.get("/dispatcharr-streams")
def get_dispatcharr_streams():
    """List available Dispatcharr streams for mapping."""
    from teamarr.database import get_db
    from teamarr.dispatcharr.factory import get_dispatcharr_connection

    try:
        dc = get_dispatcharr_connection(get_db)
        if not dc:
            return {"streams": [], "error": "Dispatcharr not configured"}

        groups = dc.m3u.list_groups()
        all_streams = []
        for group in groups:
            try:
                streams = dc.m3u.list_streams(
                    group_name=group.name, group_id=group.id
                )
                for s in streams:
                    all_streams.append({
                        "id": s.id,
                        "name": s.name,
                        "group_name": group.name,
                        "group_id": group.id,
                        "m3u_account_id": getattr(s, "m3u_account_id", None),
                    })
            except Exception:
                continue

        return {"streams": all_streams}
    except Exception as e:
        logger.warning("[EPG_SOURCES] Failed to fetch Dispatcharr streams: %s", e)
        return {"streams": [], "error": str(e)}
