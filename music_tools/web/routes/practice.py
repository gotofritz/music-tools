"""The day: what is due, one click to mark it done, and the running log.

Every route here is a call into `domain/session.py` and a render. The one that
matters is `done`: it changes three things on screen at once, which is the
whole reason there is HTMX in this app rather than a page reload per exercise.
"""

import random
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from music_tools.domain import session
from music_tools.domain.scheduling import Algorithm
from music_tools.web import views
from music_tools.web.deps import (
    fragment_or_redirect,
    get_conn,
    get_now,
    get_rng,
    render,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def today(
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """Today: the running log, the totals, and what is due."""
    return HTMLResponse(render("today.html", **views.today_context(conn, now=now)))


@router.post("/days")
def start_today(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Start the day, and set the clock running. Twice in a day is once."""
    session.start_day(conn, now=now)
    return fragment_or_redirect(request, _log_fragments(conn, now=now))


@router.post("/exercises/{exercise_id}/done")
async def done(
    request: Request,
    exercise_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
    rng: random.Random = Depends(get_rng),
) -> Response:
    """Practised it: the row's due date moves, and the day log ticks over.

    One click changes the exercise row, the log and the totals, so the row is
    the response and the other two ride along as out-of-band swaps.
    """
    algorithm = _algorithm(request, await _form(request))
    try:
        result = session.mark_done(
            conn,
            exercise_id=exercise_id,
            algorithm=algorithm,
            now=now,
            rng=rng,
        )
    except session.UnknownExercise:
        raise HTTPException(status_code=404, detail="no exercise with that id") from None

    context = views.today_context(conn, now=now)
    row = render(
        "_exercise_row.html",
        exercise=result.exercise,
        module=context["modules_by_id"][result.exercise.module_id],
        today=context["today"],
    )
    return fragment_or_redirect(request, row + _oob_fragments(context))


@router.post("/entries")
async def add_entry(
    request: Request,
    description: str = Form(...),
    log_group: str | None = Form(None),
    speed: str | None = Form(None),
    notes: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Log something the catalogue does not know about: a warm-up, a jam."""
    session.log_entry(
        conn,
        description=description,
        log_group=log_group or None,
        speed=speed or None,
        notes=notes or None,
        now=now,
    )
    return fragment_or_redirect(request, _log_fragments(conn, now=now))


@router.post("/entries/{entry_id}/stop")
def stop_entry(
    request: Request,
    entry_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Stop the clock. The unattributed tail of a session is not logged."""
    try:
        session.stop_clock(conn, entry_id=entry_id, now=now)
    except session.UnknownEntry:
        raise HTTPException(status_code=404, detail="no entry with that id") from None
    return fragment_or_redirect(request, _log_fragments(conn, now=now))


def _log_fragments(conn: sqlite3.Connection, *, now: datetime) -> str:
    """The log, with the totals and the clock swapped out of band behind it."""
    context = views.today_context(conn, now=now)
    return render("_day_log.html", **context) + _oob_fragments(context)


def _oob_fragments(context: dict) -> str:
    """Everything a write changes that is not the thing that was clicked."""
    return (
        render("_day_log.html", oob=True, **context)
        + render("_day_totals.html", oob=True, **context)
        + render("_clock.html", oob=True, **context)
    )


async def _form(request: Request) -> dict[str, str]:
    """The posted form, if there is one — `done` takes a query string too."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        return {}
    return {key: str(value) for key, value in (await request.form()).items()}


def _algorithm(request: Request, form: dict[str, str]) -> Algorithm:
    """`?algorithm=hold`, or the select in the row's form. Default NORMAL."""
    written = request.query_params.get("algorithm") or form.get("algorithm")
    if not written:
        return Algorithm.NORMAL
    try:
        return Algorithm(written)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"unknown algorithm {written!r}"
        ) from None
