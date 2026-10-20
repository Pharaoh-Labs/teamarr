"""Getting Started checklist (#818): first-run state for the Dashboard card."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.database.settings import update_display_settings
from teamarr.dispatcharr.factory import DispatcharrFactory
from teamarr.services.setup_status import compute_setup_status

router = APIRouter()


def _probe_dispatcharr() -> tuple[bool, bool]:
    """``(configured, connected)`` from the memoised liveness probe (#736)."""
    factory = DispatcharrFactory(get_db)
    if not factory.is_configured:
        return False, False
    return True, bool(factory.probe_connection().success)


@router.get("/setup/status")
def get_setup_status() -> dict:
    """The six facts behind the Getting Started checklist, plus whether to show it.

    ``visible`` is false once the install is working (a completed run and
    active channels) or the user dismissed the card.
    """
    with get_db() as conn:
        return compute_setup_status(conn, _probe_dispatcharr).to_dict()


@router.post("/setup/getting-started/dismiss")
def dismiss_getting_started() -> dict:
    """Close the Getting Started card for this install."""
    with get_db() as conn:
        update_display_settings(conn, getting_started_dismissed=True)
    return {"dismissed": True}


@router.post("/setup/getting-started/restore")
def restore_getting_started() -> dict:
    """Bring the Getting Started card back (it still hides once setup is complete)."""
    with get_db() as conn:
        update_display_settings(conn, getting_started_dismissed=False)
    return {"dismissed": False}
