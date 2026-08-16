"""The catalogue: a module's queue, and editing a row without leaving it.

`PATCH /exercises/{id}` is registered for `POST` as well. HTML forms only send
GET and POST, so the same handler answers both: with JavaScript HTMX sends the
PATCH, and without it the form still submits.
"""

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from music_tools.db import repository as repo
from music_tools.domain import catalogue
from music_tools.domain.models import Exercise, Module
from music_tools.domain.session import practice_day_for
from music_tools.domain.tempo import format_tempo, parse_tempo
from music_tools.web import views
from music_tools.web.deps import fragment_or_redirect, get_conn, get_now, render

router = APIRouter()


@router.get("/modules/{slug}", response_class=HTMLResponse)
def module_page(
    slug: str,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """One module's whole queue, most overdue first."""
    module = _module(conn, slug)
    return HTMLResponse(
        render(
            "module.html",
            module=module,
            exercises=repo.exercises_due(conn, module_id=module.id),
            modules_by_id=views.modules_by_id(conn),
            **views.chrome(conn, now=now),
        )
    )


@router.api_route("/exercises/{exercise_id}", methods=["PATCH", "POST"])
def edit_exercise(
    request: Request,
    exercise_id: int,
    name: str | None = Form(None),
    speed: str | None = Form(None),
    target_bpm: str | None = Form(None),
    style: str | None = Form(None),
    notes: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Edit a row in place, and hand back the row as it now reads."""
    fields = _fields(
        name=name, speed=speed, target_bpm=target_bpm, style=style, notes=notes
    )
    try:
        exercise = catalogue.update_exercise(conn, exercise_id, **fields)
    except catalogue.NotFound:
        raise HTTPException(
            status_code=404, detail="no exercise with that id"
        ) from None
    except catalogue.InUse as clash:
        raise HTTPException(status_code=409, detail=str(clash)) from None
    return fragment_or_redirect(request, _row(conn, exercise, now=now))


@router.post("/exercises")
def add_exercise(
    request: Request,
    module_id: int = Form(...),
    name: str = Form(...),
    speed: str | None = Form(None),
    target_bpm: str | None = Form(None),
    style: str | None = Form(None),
    notes: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Add a row to a module, due today.

    Everything that asks what is due reads a date — `practice next`, the due
    count on `module list` — so an undated row is invisible to all of them. A
    row typed in during a session is something to play in that session.
    """
    fields = _fields(speed=speed, target_bpm=target_bpm, style=style, notes=notes)
    try:
        exercise = catalogue.add_exercise(
            conn,
            module_id=module_id,
            name=name,
            next_due=practice_day_for(now),
            **fields,
        )
    except catalogue.NotFound:
        raise HTTPException(status_code=404, detail="no module with that id") from None
    except catalogue.InUse as clash:
        raise HTTPException(status_code=409, detail=str(clash)) from None
    return fragment_or_redirect(request, _row(conn, exercise, now=now))


@router.get("/exercises/{exercise_id}/tempo", response_class=HTMLResponse)
def tempo(
    exercise_id: int,
    written: str = "",
    speed: str | None = None,
    target_bpm: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> HTMLResponse:
    """What a speed resolves to, live, while it is being typed.

    `written` is the plain form of the question; `speed` and `target_bpm` are
    what the row's own inputs are called, so the two fields being edited
    resolve against each other rather than against what is stored.

    Half-typed input is not an error — it is a keystroke — so anything
    unreadable comes back as a quiet `?`.
    """
    exercise = repo.get_exercise(conn, exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="no exercise with that id")
    target = exercise.target_bpm
    if target_bpm is not None and target_bpm.strip():
        try:
            target = float(target_bpm)
        except ValueError:
            target = None  # also a keystroke, also not an error
    resolved = parse_tempo(speed if speed is not None else written, target_bpm=target)
    text = "?" if resolved.bpm is None else format_tempo(resolved)
    return HTMLResponse(render("_tempo.html", text=text))


def _module(conn: sqlite3.Connection, slug: str) -> Module:
    module = repo.find_module(conn, slug)
    if module is None or module.archived_at is not None:
        raise HTTPException(status_code=404, detail=f"no module called {slug}")
    return module


def _row(conn: sqlite3.Connection, exercise: Exercise, *, now: datetime) -> str:
    """The row fragment HTMX swaps back in over the one that was edited."""
    return render(
        "_exercise_row.html",
        exercise=exercise,
        module=views.modules_by_id(conn)[exercise.module_id],
        **views.chrome(conn, now=now),
    )


def _fields(**posted: str | None) -> dict[str, object]:
    """What the form actually sent. A field left out is left alone.

    An empty string is a field cleared, except for `target_bpm`, which is a
    number: it is either given or absent.
    """
    fields: dict[str, object] = {}
    for key, value in posted.items():
        if value is None:
            continue
        if key == "target_bpm":
            if value.strip():
                fields[key] = float(value)
            continue
        fields[key] = value
    return fields
