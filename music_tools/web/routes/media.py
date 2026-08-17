"""The material an exercise is practised from: serving it, and attaching it.

Serving is deliberately thin. A bare `<audio>` needs a URL, so one exists;
Phase 5 is where it grows a render cache, speed and pitch, and the range
handling Safari insists on. What it already has is the guard every path in this
app goes through: a source's path is re-checked against the configured roots as
it is served, not only as it was attached, because the roots can be narrowed
after the fact and a stored path is not a promise.
"""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from music_tools.db import repository as repo
from music_tools.domain import media
from music_tools.web.deps import get_conn

router = APIRouter()


@router.get("/media/{source_id}/file")
def media_file(
    source_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> FileResponse:
    """The file itself, as it sits on disk. Never copied, only read.

    `FileResponse` answers range requests on its own, which is what a browser
    seeking through a track sends.
    """
    source = repo.get_media_source(conn, source_id)
    if source is None or source.path is None:
        raise HTTPException(status_code=404, detail="no media with that id")
    try:
        path = media.resolve_within_roots(source.path)
    except media.OutsideRoots as outside:
        raise HTTPException(status_code=403, detail=str(outside)) from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{source.path} is not there")
    return FileResponse(path, filename=Path(path).name)
