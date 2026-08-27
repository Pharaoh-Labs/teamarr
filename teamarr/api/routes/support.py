"""Share-safe support bundle download endpoint."""

from datetime import datetime

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from teamarr.services.support_bundle import SupportBundleService

router = APIRouter(prefix="/support")


@router.get("/bundle")
async def download_support_bundle() -> Response:
    """Download a redacted diagnostic archive without changing application state."""
    content = await run_in_threadpool(SupportBundleService().create)
    filename = datetime.now().strftime("teamarr-support-%Y%m%d-%H%M%S.zip")
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
