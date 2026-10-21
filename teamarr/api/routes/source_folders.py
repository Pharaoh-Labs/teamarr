"""Sources page folders and arrangement (#1110).

Everything here is cosmetic. Folders, their order and each source's place
in them are how the Sources table is arranged; the run reads sources by id
and stream priority never looks at any of it (#1109). The auto-arrange
actions are one-time and repeatable, never scheduled, and every one of them
(and Remove all folders) writes a one-level undo snapshot first.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from teamarr.database import get_db
from teamarr.database.source_folders import (
    arrange_by_evidence,
    arrange_by_provider,
    clear_folders,
    create_folder,
    delete_folder,
    get_folder,
    has_undo,
    list_folders,
    restore_arrangement,
    set_arrangement,
    update_folder,
)

router = APIRouter()


class SourceFolderResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    collapsed: bool


class SourceFolderListResponse(BaseModel):
    folders: list[SourceFolderResponse]
    can_undo: bool


class SourceFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SourceFolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    collapsed: bool | None = None


class SourcePlacement(BaseModel):
    group_id: int
    folder_id: int | None = None
    sort_order: int


class FolderPlacement(BaseModel):
    folder_id: int
    sort_order: int


class ArrangementRequest(BaseModel):
    sources: list[SourcePlacement]
    folders: list[FolderPlacement] = Field(default_factory=list)


class ArrangementResponse(BaseModel):
    updated: int


class ArrangeRequest(BaseModel):
    by: str = Field(pattern="^(provider|sport|league)$")


class ArrangeResponse(BaseModel):
    folders: int
    filed: int
    unfiled: int
    can_undo: bool


def _listing(conn) -> SourceFolderListResponse:
    return SourceFolderListResponse(
        folders=[SourceFolderResponse(**f.to_dict()) for f in list_folders(conn)],
        can_undo=has_undo(conn),
    )


@router.get("", response_model=SourceFolderListResponse)
def list_source_folders():
    """List the Sources page folders in display order, and whether an undo is waiting."""
    with get_db() as conn:
        return _listing(conn)


@router.post("", response_model=SourceFolderResponse, status_code=status.HTTP_201_CREATED)
def create_source_folder(request: SourceFolderCreate):
    """Create an empty folder at the end of the list."""
    with get_db() as conn:
        try:
            folder = create_folder(conn, request.name)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return SourceFolderResponse(**folder.to_dict())


@router.patch("/{folder_id}", response_model=SourceFolderResponse)
def update_source_folder(folder_id: int, request: SourceFolderUpdate):
    """Rename a folder or remember whether it is collapsed."""
    with get_db() as conn:
        if get_folder(conn, folder_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
        try:
            folder = update_folder(conn, folder_id, name=request.name, collapsed=request.collapsed)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        assert folder is not None
        return SourceFolderResponse(**folder.to_dict())


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_folder(folder_id: int):
    """Delete a folder. Its sources move to the top level and keep their positions."""
    with get_db() as conn:
        if not delete_folder(conn, folder_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")


@router.put("/arrangement", response_model=ArrangementResponse)
def put_arrangement(request: ArrangementRequest):
    """Store the arrangement after a drag: each source's folder and position,
    and the folders' own order. Display only (#1109)."""
    with get_db() as conn:
        updated = set_arrangement(
            conn,
            [(s.group_id, s.folder_id, s.sort_order) for s in request.sources],
            [(f.folder_id, f.sort_order) for f in request.folders],
        )
        return ArrangementResponse(updated=updated)


@router.post("/arrange", response_model=ArrangeResponse)
def arrange(request: ArrangeRequest):
    """Rebuild the folders from the sources' provider, or from their last-run
    matches by sport or league (top one at 80% or more, else Multi; no
    matches stays at the top level). One-time and repeatable; snapshots the
    previous arrangement for Undo first."""
    with get_db() as conn:
        if request.by == "provider":
            result = arrange_by_provider(conn)
        else:
            result = arrange_by_evidence(conn, request.by)
        return ArrangeResponse(
            folders=result.folders,
            filed=result.filed,
            unfiled=result.unfiled,
            can_undo=has_undo(conn),
        )


@router.post("/undo", response_model=SourceFolderListResponse)
def undo_arrangement():
    """Restore the arrangement from before the last arrange or clear action."""
    with get_db() as conn:
        if not restore_arrangement(conn):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to undo")
        return _listing(conn)


@router.post("/clear", response_model=SourceFolderListResponse)
def clear_source_folders():
    """Remove every folder; sources keep their positions at the top level. Undoable."""
    with get_db() as conn:
        clear_folders(conn)
        return _listing(conn)
