"""Exception keywords API endpoints.

Provides REST API for managing consolidation exception keywords.
These keywords control how duplicate streams are handled during event matching.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from teamarr.database import get_db
from teamarr.database.exception_keywords import (
    ExceptionKeyword,
    get_all_keywords,
    set_keyword_enabled,
)
from teamarr.database.exception_keywords import (
    create_keyword as db_create_keyword,
)
from teamarr.database.exception_keywords import (
    delete_keyword as db_delete_keyword,
)
from teamarr.database.exception_keywords import (
    get_keyword as db_get_keyword,
)
from teamarr.database.exception_keywords import (
    update_keyword as db_update_keyword,
)

router = APIRouter()


ExceptionBehavior = Literal["consolidate", "separate", "ignore"]


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class SourceRef(BaseModel):
    """A picked M3U group or stream; ``name`` is a display snapshot."""

    id: int
    name: str | None = None


def _validate_pattern(value: str | None) -> str | None:
    """Reject a regex Python can't compile (the API answers 400, not 422)."""
    import re

    if value is None or not value.strip():
        return value
    try:
        re.compile(value)
    except re.error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regular expression {value!r}: {e}",
        ) from e
    return value


class _MatchSources(BaseModel):
    """Match sources beyond stream-name terms (#893)."""

    m3u_group_pattern: str | None = Field(
        None, description="Regex on the stream's M3U group name (case-insensitive search)"
    )
    m3u_groups: list[SourceRef] | None = Field(None, description="Picked Dispatcharr M3U groups")
    stream_pattern: str | None = Field(
        None, description="Regex on the stream name (case-insensitive search)"
    )
    streams: list[SourceRef] | None = Field(None, description="Picked Dispatcharr streams")
    event_group_ids: list[int] | None = Field(
        None, description="Teamarr event groups whose streams get this keyword"
    )

    def has_source(self) -> bool:
        return bool(
            (self.m3u_group_pattern or "").strip()
            or (self.stream_pattern or "").strip()
            or self.m3u_groups
            or self.streams
            or self.event_group_ids
        )

    def source_kwargs(self) -> dict:
        return {
            "m3u_group_pattern": _validate_pattern(self.m3u_group_pattern),
            "m3u_groups": _dump_refs(self.m3u_groups),
            "stream_pattern": _validate_pattern(self.stream_pattern),
            "streams": _dump_refs(self.streams),
            "event_group_ids": self.event_group_ids,
        }


def _dump_refs(refs: list[SourceRef] | None) -> list[dict] | None:
    return None if refs is None else [r.model_dump() for r in refs]


class ExceptionKeywordCreate(_MatchSources):
    """Create exception keyword request."""

    label: str = Field(
        ...,
        min_length=1,
        description="Label for channel naming and {exception_keyword} template variable (e.g., 'Spanish', 'Manningcast')",  # noqa: E501
    )
    match_terms: str = Field(
        "",
        description="Comma-separated terms/phrases to match in stream names (e.g., 'Spanish, En Español, (ESP)'); may be empty when another match source is set",  # noqa: E501
    )
    behavior: ExceptionBehavior = Field(
        default="consolidate",
        description="How to handle matched streams",
    )
    enabled: bool = True


class ExceptionKeywordUpdate(_MatchSources):
    """Update exception keyword request.

    Omitted fields are left alone; an empty string/list clears a source.
    """

    label: str | None = Field(None, min_length=1)
    match_terms: str | None = None
    behavior: ExceptionBehavior | None = None
    enabled: bool | None = None

    @field_validator("match_terms")
    @classmethod
    def _strip_terms(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None


class ExceptionKeywordResponse(BaseModel):
    """Exception keyword response."""

    id: int
    label: str
    match_terms: str
    match_term_list: list[str]
    behavior: str
    enabled: bool
    created_at: str | None = None
    m3u_group_pattern: str | None = None
    m3u_groups: list[SourceRef] = []
    stream_pattern: str | None = None
    streams: list[SourceRef] = []
    event_group_ids: list[int] = []


def _to_response(kw: ExceptionKeyword) -> "ExceptionKeywordResponse":
    assert kw.id is not None  # persisted rows always have an id
    return ExceptionKeywordResponse(
        id=kw.id,
        label=kw.label,
        match_terms=kw.match_terms,
        match_term_list=kw.match_term_list,
        behavior=kw.behavior,
        enabled=kw.enabled,
        created_at=kw.created_at.isoformat() if kw.created_at else None,
        m3u_group_pattern=kw.m3u_group_pattern,
        m3u_groups=[SourceRef(**g) for g in kw.m3u_groups if isinstance(g.get("id"), int)],
        stream_pattern=kw.stream_pattern,
        streams=[SourceRef(**st) for st in kw.streams if isinstance(st.get("id"), int)],
        event_group_ids=kw.event_group_ids,
    )


def _require_source(match_terms: str, sources: _MatchSources) -> None:
    if not match_terms.strip() and not sources.has_source():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A keyword needs match terms or at least one other match source",
        )


class ExceptionKeywordListResponse(BaseModel):
    """List of exception keywords."""

    keywords: list[ExceptionKeywordResponse]
    total: int


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=ExceptionKeywordListResponse)
def list_keywords(
    include_disabled: bool = Query(False, description="Include disabled keywords"),
):
    """List all exception keywords."""

    with get_db() as conn:
        keywords = get_all_keywords(conn, include_disabled=include_disabled)

    responses = [_to_response(kw) for kw in keywords]

    return ExceptionKeywordListResponse(
        keywords=responses,
        total=len(keywords),
    )


@router.get("/{keyword_id}", response_model=ExceptionKeywordResponse)
def get_keyword(keyword_id: int):
    """Get a single exception keyword by ID."""

    with get_db() as conn:
        keyword = db_get_keyword(conn, keyword_id)

    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Keyword {keyword_id} not found",
        )

    return _to_response(keyword)


@router.post("", response_model=ExceptionKeywordResponse, status_code=status.HTTP_201_CREATED)
def create_keyword(request: ExceptionKeywordCreate):
    """Create a new exception keyword."""
    import sqlite3


    _require_source(request.match_terms, request)
    sources = request.source_kwargs()
    try:
        with get_db() as conn:
            keyword_id = db_create_keyword(
                conn,
                label=request.label,
                match_terms=request.match_terms.strip(),
                behavior=request.behavior,
                enabled=request.enabled,
                **sources,
            )
            keyword = db_get_keyword(conn, keyword_id)
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Label '{request.label}' already exists",
        ) from e

    if keyword is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keyword could not be retrieved after creation",
        )

    return _to_response(keyword)


@router.put("/{keyword_id}", response_model=ExceptionKeywordResponse)
def update_keyword(keyword_id: int, request: ExceptionKeywordUpdate):
    """Update an exception keyword."""
    import sqlite3


    try:
        with get_db() as conn:
            keyword = db_get_keyword(conn, keyword_id)
            if not keyword:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Keyword {keyword_id} not found",
                )

            sources = request.source_kwargs()
            merged = _MatchSources(
                m3u_group_pattern=_pick(request.m3u_group_pattern, keyword.m3u_group_pattern),
                m3u_groups=_pick(request.m3u_groups, keyword.m3u_groups or None),
                stream_pattern=_pick(request.stream_pattern, keyword.stream_pattern),
                streams=_pick(request.streams, keyword.streams or None),
                event_group_ids=_pick(request.event_group_ids, keyword.event_group_ids or None),
            )
            _require_source(_pick(request.match_terms, keyword.match_terms) or "", merged)

            db_update_keyword(
                conn,
                keyword_id,
                label=request.label,
                match_terms=request.match_terms,
                behavior=request.behavior,
                enabled=request.enabled,
                **sources,
            )
            keyword = db_get_keyword(conn, keyword_id)
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Label '{request.label}' already exists",
        ) from e

    if keyword is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Keyword could not be retrieved after update",
        )

    return _to_response(keyword)


def _pick(new, current):
    """The value after an update: ``new`` when provided, else ``current``."""
    return current if new is None else new


@router.patch("/{keyword_id}/enabled")
def toggle_keyword(keyword_id: int, enabled: bool = Query(...)) -> dict:
    """Enable or disable an exception keyword."""

    with get_db() as conn:
        keyword = db_get_keyword(conn, keyword_id)
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Keyword {keyword_id} not found",
            )

        set_keyword_enabled(conn, keyword_id, enabled)

    return {"id": keyword_id, "enabled": enabled}


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_keyword(keyword_id: int):
    """Delete an exception keyword."""

    with get_db() as conn:
        keyword = db_get_keyword(conn, keyword_id)
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Keyword {keyword_id} not found",
            )

        db_delete_keyword(conn, keyword_id)
