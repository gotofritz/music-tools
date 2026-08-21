"""The material an exercise is practised from: serving it, and attaching it.

Serving is deliberately thin. A bare `<audio>` needs a URL, so one exists;
Phase 5 is where it grows a render cache, speed and pitch, and the range
handling Safari insists on. What it already has is the guard every path in this
app goes through: a source's path is re-checked against the configured roots as
it is served, not only as it was attached, because the roots can be narrowed
after the fact and a stored path is not a promise.

The attaching half is a page per exercise. Paths are typed rather than picked
from a tree — browsing the filesystem from the browser belongs to the parked
loop-editor plan — so the page says which roots a path may point into and the
domain refuses anything else. A refusal is a message on the page: a mistyped
path is a mistake to fix, not an error to hide.
"""

import mimetypes
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from music_tools.db import repository as repo
from music_tools.domain import media
from music_tools.domain.models import Exercise, MediaSource
from music_tools.web import views
from music_tools.web.deps import fragment_or_redirect, get_conn, get_now, render

router = APIRouter()

#: What a browser would *run* rather than show. Everything else is served
#: inline, so a click opens the score in whatever the machine opens it with
#: instead of dropping it in the downloads folder — but these come back as a
#: download: the app is the origin they would run in, and a page that can
#: script can talk to the app as the app.
SCRIPTABLE = (
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "application/xml",
    "text/xml",
)


@router.get("/media/{source_id}/file")
def media_file(
    source_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> FileResponse:
    """The file itself, as it sits on disk. Never copied, only read.

    `FileResponse` answers range requests on its own, which is what a browser
    seeking through a track sends. It is served **inline**, so following the
    link on the page opens the tune's score in whatever the machine opens a
    PDF or a `.mscz` with, rather than saving a second copy of a file that was
    never copied in the first place. Anything that scripts is the exception —
    see `SCRIPTABLE`.
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
    return FileResponse(
        path, filename=Path(path).name, content_disposition_type=_disposition(path)
    )


@router.get("/exercises/{exercise_id}/media", response_class=HTMLResponse)
def media_page(
    exercise_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """Everything attached to one exercise, and the forms that add more."""
    exercise = _exercise(conn, exercise_id)
    return HTMLResponse(
        render(
            "media.html",
            exercise=exercise,
            module=views.modules_by_id(conn)[exercise.module_id],
            roots=media.media_roots(),
            cards=media.exercise_media(conn, exercise_id=exercise.id),
            **views.chrome(conn, now=now),
        )
    )


@router.post("/exercises/{exercise_id}/media")
def attach(
    request: Request,
    exercise_id: int,
    kind: str = Form(...),
    path: str | None = Form(None),
    url: str | None = Form(None),
    body: str | None = Form(None),
    label: str | None = Form(None),
    group_id: int | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Attach one thing to an exercise: a file, a URL, a score, some text.

    A file with a `group_id` joins that track set, which is where the two
    checks on a set live; without one it gets a group of its own.
    """
    with _reporting():
        media.attach(
            conn,
            exercise_id=exercise_id,
            kind=kind,
            path=path or None,
            url=url or None,
            body=body or None,
            label=label or None,
            group_id=group_id,
            now=now,
        )
    return fragment_or_redirect(request, _list(conn, exercise_id))


@router.api_route("/media/{source_id}", methods=["DELETE"])
@router.post("/media/{source_id}/delete")
def detach(
    request: Request,
    source_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Take an attachment off an exercise. The file itself is left alone.

    HTMX sends the `DELETE`; the `/delete` path is the same handler for a
    plain form, which can only manage GET and POST.
    """
    source = _source(conn, source_id)
    with _reporting():
        media.detach(conn, source_id=source_id)
    return fragment_or_redirect(request, _list(conn, source.exercise_id))


@router.post("/media/{source_id}/move")
def move(
    request: Request,
    source_id: int,
    direction: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Move a card one place up or down the exercise."""
    source = _source(conn, source_id)
    try:
        media.move(conn, source_id=source_id, direction=direction)
    except ValueError as unknown:
        raise HTTPException(status_code=400, detail=str(unknown)) from None
    return fragment_or_redirect(request, _list(conn, source.exercise_id))


@router.api_route("/media/{source_id}", methods=["PATCH", "POST"])
def describe(
    request: Request,
    source_id: int,
    label: str | None = Form(None),
    gain: float | None = Form(None),
    pan: float | None = Form(None),
    muted: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Name a track, and set where it sits in the mix.

    `muted` is a checkbox, so its absence is a real answer — unlike the two
    numbers, where absence means "leave it alone".
    """
    source = _source(conn, source_id)
    with _reporting():
        media.describe(
            conn,
            source_id=source_id,
            label=label or None,
            gain=gain,
            pan=pan,
            muted=muted,
        )
    return fragment_or_redirect(request, _list(conn, source.exercise_id))


@router.post("/groups/{group_id}/label")
def label_set(
    request: Request,
    group_id: int,
    label: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Name a set as a whole: "stems", "with click"."""
    group = repo.get_media_group(conn, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="no track set with that id")
    media.label_set(conn, group_id=group_id, label=label or None)
    return fragment_or_redirect(request, _list(conn, group.exercise_id))


@contextmanager
def _reporting() -> Iterator[None]:
    """Turn the domain's refusals into status codes, here and only here.

    A path that is wrong or missing is something the player typed and can
    retype: 400, with the message the domain wrote. A set that will not take
    another member is a collision with what is already there: 409, like every
    other `InUse` in this app.
    """
    try:
        yield
    except media.NotFound:
        raise HTTPException(
            status_code=404, detail="no exercise with that id"
        ) from None
    except media.UnknownMedia:
        raise HTTPException(status_code=404, detail="no media with that id") from None
    except (media.SetTooBig, media.MembersDisagree) as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None
    except (media.OutsideRoots, media.MissingFile, media.BadMedia) as wrong:
        raise HTTPException(status_code=400, detail=str(wrong)) from None


def _disposition(path: Path) -> str:
    """`inline` for the tune's material, `attachment` for what would script."""
    guessed, _ = mimetypes.guess_type(path.name)
    return "attachment" if guessed in SCRIPTABLE else "inline"


def _exercise(conn: sqlite3.Connection, exercise_id: int) -> Exercise:
    exercise = repo.get_exercise(conn, exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="no exercise with that id")
    return exercise


def _source(conn: sqlite3.Connection, source_id: int) -> MediaSource:
    source = repo.get_media_source(conn, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="no media with that id")
    return source


def _list(conn: sqlite3.Connection, exercise_id: int) -> str:
    """The attachment list, as it now reads: what every write answers with."""
    return render(
        "_media_list.html",
        exercise=_exercise(conn, exercise_id),
        cards=media.exercise_media(conn, exercise_id=exercise_id),
    )
