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

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, HTMLResponse, Response

from music_tools.db import repository as repo
from music_tools.domain import media, waveform
from music_tools.domain import render as renders
from music_tools.domain.models import Exercise, MediaSource
from music_tools.web import views
from music_tools.web.deps import (
    exercise_ratio,
    fragment_or_redirect,
    get_conn,
    get_now,
    render,
)

router = APIRouter()

#: The element id (as HTMX sends it in `HX-Target`) of the running card's list.
NOW_MEDIA_LIST = "now-media-list"


def _playable_path(conn: sqlite3.Connection, source_id: int) -> Path:
    """The file a media row points at, guarded the way every path in is.

    Re-checked against the roots on every request, because the roots can be
    narrowed after a row was written. A file that has gone is a 409 naming the
    path rather than a stack trace.
    """
    source = repo.get_media_source(conn, source_id)
    if source is None or source.path is None:
        raise HTTPException(status_code=404, detail="no media with that id")
    try:
        path = media.resolve_within_roots(source.path)
    except media.OutsideRoots as outside:
        raise HTTPException(status_code=403, detail=str(outside)) from None
    if not path.is_file():
        # The row is fine and the world has moved: a collision with what the
        # database remembers, so 409 with the path to go and look for.
        raise HTTPException(status_code=409, detail=f"{source.path} is not there")
    return path


@router.get("/media/{source_id}/file")
def media_file(
    source_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> FileResponse:
    """The file itself, as it sits on disk. Never copied, only read.

    `FileResponse` answers range requests on its own — `Accept-Ranges: bytes`,
    206 with `Content-Range`, 416 past the end — which Safari insists on and
    every browser seeking through a track sends.
    """
    path = _playable_path(conn, source_id)
    return FileResponse(path, filename=Path(path).name)


@router.get("/media/{source_id}/audio")
def media_audio(
    source_id: int,
    speed: float = Query(1.0, ge=renders.MIN_SPEED, le=renders.MAX_SPEED),
    semitones: int = Query(0, ge=-renders.MAX_SEMITONES, le=renders.MAX_SEMITONES),
    mono: bool = Query(False),
    conn: sqlite3.Connection = Depends(get_conn),
) -> FileResponse:
    """What the player plays: the file's audio, at `speed` and `semitones`.

    A video is extracted, and speed, pitch and a `mono` downmix (what a member
    of a set is played as) are one render, all through the cache; a plain
    audio file at full speed, no shift and stereo is served as it sits. Ranges
    come with `FileResponse`, from the cache as from the roots.
    """
    path = _playable_path(conn, source_id)
    with _rendering(path):
        audio = renders.playable_audio(
            path,
            speed=speed,
            semitones=semitones,
            mono=mono,
            cache=renders.cache_dir(),
        )
    return FileResponse(audio, filename=audio.name)


@router.get("/media/{source_id}/peaks")
def media_peaks(
    source_id: int,
    buckets: int = Query(2000, ge=1, le=10_000),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, object]:
    """The waveform as `buckets` min/max pairs, and the length in seconds."""
    path = _playable_path(conn, source_id)
    with _rendering(path):
        return {
            "duration": renders.duration_seconds(path),
            "peaks": waveform.peaks(path, buckets=buckets, cache=renders.cache_dir()),
        }


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
    background: BackgroundTasks,
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
    checks on a set live; without one it gets a group of its own. Its set is
    then rendered at the common speeds behind the answer (`_prerender`).
    """
    with _reporting():
        source = media.attach(
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
    if request.app.state.prerender and source.group_id is not None:
        _prerender(conn, background, group_id=source.group_id)
    return fragment_or_redirect(
        request, _list(request, conn, exercise_id, players=True, now=now)
    )


def _prerender(
    conn: sqlite3.Connection, background: BackgroundTasks, *, group_id: int
) -> None:
    """Render a set at the speeds the slider will ask for, after answering.

    Every member, because a second track turns a stereo lone file into a mono
    member of a set and its renders with it. The speeds are `LADDER` plus the
    exercise's own, so the slider's first position is a hit too.
    """
    members = repo.media_sources_in_group(conn, group_id=group_id)
    paths = []
    for member in members:
        try:
            paths.append(_playable_path(conn, member.id))
        except HTTPException:
            continue  # gone or out of bounds: the player will say so when asked
    ratio = exercise_ratio(repo.get_exercise(conn, members[0].exercise_id))
    background.add_task(
        renders.prerender,
        paths,
        speeds=renders.speed_ladder(ratio),
        mono=len(members) > 1,
        cache=renders.cache_dir(),
    )


@router.api_route("/media/{source_id}", methods=["DELETE"])
@router.post("/media/{source_id}/delete")
def detach(
    request: Request,
    source_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Take an attachment off an exercise. The file itself is left alone.

    HTMX sends the `DELETE`; the `/delete` path is the same handler for a
    plain form, which can only manage GET and POST.
    """
    source = _source(conn, source_id)
    with _reporting():
        media.detach(conn, source_id=source_id)
    return fragment_or_redirect(
        request, _list(request, conn, source.exercise_id, players=True, now=now)
    )


@router.post("/media/{source_id}/move")
def move(
    request: Request,
    source_id: int,
    direction: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Move a card one place up or down the exercise."""
    source = _source(conn, source_id)
    try:
        media.move(conn, source_id=source_id, direction=direction)
    except ValueError as unknown:
        raise HTTPException(status_code=400, detail=str(unknown)) from None
    return fragment_or_redirect(
        request, _list(request, conn, source.exercise_id, players=True, now=now)
    )


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
    return fragment_or_redirect(request, _list(request, conn, source.exercise_id))


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
    return fragment_or_redirect(request, _list(request, conn, group.exercise_id))


@contextmanager
def _rendering(path: Path) -> Iterator[None]:
    """A file the roots allow and ffmpeg cannot read is a 409 naming it."""
    try:
        yield
    except renders.RenderError as failed:
        message = str(failed)
        raise HTTPException(
            status_code=409,
            detail=message if str(path) in message else f"{path}: {message}",
        ) from None


@contextmanager
def _reporting() -> Iterator[None]:
    """Turn the domain's refusals into status codes, here and only here.

    A path that is wrong or missing is something the player typed and can
    retype: 400, with the message the domain wrote. A set that will not take
    another member, or a file that is already attached, is a collision with what
    is already there: 409, like every other `InUse` in this app.
    """
    try:
        yield
    except media.NotFound:
        raise HTTPException(
            status_code=404, detail="no exercise with that id"
        ) from None
    except media.UnknownMedia:
        raise HTTPException(status_code=404, detail="no media with that id") from None
    except (
        media.DuplicateMedia,
        media.SetTooBig,
        media.MembersDisagree,
    ) as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None
    except (media.OutsideRoots, media.MissingFile, media.BadMedia) as wrong:
        raise HTTPException(status_code=400, detail=str(wrong)) from None


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


def _list(
    request: Request,
    conn: sqlite3.Connection,
    exercise_id: int,
    *,
    players: bool = False,
    now: datetime | None = None,
) -> str:
    """The attachment list, as it now reads: what every write answers with.

    Aimed at the running card (`HX-Target: now-media-list`) the list keeps the
    card's id. A write that changed the source set — `players` — also swaps the
    card's players out of band, so a new file gets its waveform and a removed
    one stops; a label or a gain leaves them, and the audio playing in them,
    where they are.
    """
    exercise = _exercise(conn, exercise_id)
    cards = media.exercise_media(conn, exercise_id=exercise_id)
    if request.headers.get("HX-Target") != NOW_MEDIA_LIST:
        return render("_media_list.html", exercise=exercise, cards=cards)
    html = render(
        "_media_list.html", exercise=exercise, cards=cards, list_id=NOW_MEDIA_LIST
    )
    if players and now is not None:
        running = views.running_entry(conn, now=now)
        if running is not None and running.exercise_id == exercise.id:
            html += render(
                "_media_players.html",
                oob=True,
                cards=cards,
                running_exercise=exercise,
            )
    return html
