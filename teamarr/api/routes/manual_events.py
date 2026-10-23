"""API-first manual fixture management; normal generation owns all side effects."""

from fastapi import APIRouter, HTTPException

from teamarr.database import get_db
from teamarr.database.manual_events import get_manual_event, list_manual_events
from teamarr.database.provider_cache import event_to_dict
from teamarr.services.manual_events import (
    ManualFixtureInput,
    cancel_manual_fixture,
    write_manual_fixture,
)

router = APIRouter()


@router.get("")
def list_fixtures(league: str | None = None) -> dict:
    with get_db() as conn:
        events = list_manual_events(conn, league)
    return {"events": [event_to_dict(event) for event in events], "total": len(events)}


@router.post("", status_code=201)
def create_fixture(data: ManualFixtureInput) -> dict:
    try:
        with get_db() as conn:
            event = write_manual_fixture(conn, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return event_to_dict(event)


@router.get("/{event_id}")
def read_fixture(event_id: str, league: str | None = None) -> dict:
    """The id is a globally unique surrogate key; league is an optional check."""
    with get_db() as conn:
        event = get_manual_event(conn, event_id, league)
    if event is None:
        raise HTTPException(status_code=404, detail="Manual fixture not found")
    return event_to_dict(event)


@router.put("/{event_id}")
def replace_fixture(event_id: str, data: ManualFixtureInput) -> dict:
    try:
        with get_db() as conn:
            event = write_manual_fixture(conn, data, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return event_to_dict(event)


@router.delete("/{event_id}")
def cancel_fixture(event_id: str, league: str | None = None) -> dict:
    """Idempotently soft-cancel an existing fixture; never erase identity or
    delete Dispatcharr state here."""
    try:
        with get_db() as conn:
            event = cancel_manual_fixture(conn, event_id, league)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return event_to_dict(event)
