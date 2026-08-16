"""The day: the running log, the days behind it, and marking things done.

Every route here is a call into `domain/session.py` and a render. The one that
matters is `done`: it changes three things on screen at once, which is the
whole reason there is HTMX in this app rather than a page reload per exercise.
"""

import random
import sqlite3
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from music_tools.db import repository as repo
from music_tools.domain import session
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import practice_day_for
from music_tools.web import views
from music_tools.web.deps import (
    fragment_or_redirect,
    get_conn,
    get_now,
    get_rng,
    is_htmx,
    render,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def today(
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """Today: the running log, the totals, and the days before this one."""
    return HTMLResponse(render("today.html", **views.today_context(conn, now=now)))


@router.get("/days", response_class=HTMLResponse)
def earlier_days(
    request: Request,
    before: date,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """The next page of finished days, older than `before`.

    HTMX asks for the page on its own and swaps it in place of the button it
    came from; a browser with no JavaScript follows the same URL as a link and
    gets a page of history with a button of its own.
    """
    context = views.history_context(conn, now=now, before=before)
    if is_htmx(request):
        return HTMLResponse(render("_history_page.html", **context))
    return HTMLResponse(
        render("history.html", before=before, **views.chrome(conn, now=now), **context)
    )


@router.get("/days/{day}", response_class=HTMLResponse)
def one_day(
    request: Request,
    day: date,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """One day, as written. The way back out of edit mode."""
    return _day_view(request, conn, day=day, now=now, editing=False)


@router.get("/days/{day}/edit", response_class=HTMLResponse)
def edit_one_day(
    request: Request,
    day: date,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> HTMLResponse:
    """The same day with boxes round its lines, one day at a time.

    Editing is per day and asked for: the log is read by default, and a page
    of input boxes reads like a form rather than a record of practice.
    """
    return _day_view(request, conn, day=day, now=now, editing=True)


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
        raise HTTPException(
            status_code=404, detail="no exercise with that id"
        ) from None

    context = views.today_context(conn, now=now)
    row = render(
        "_exercise_row.html",
        exercise=result.exercise,
        module=context["modules_by_id"][result.exercise.module_id],
        today=context["today"],
    )
    response = row + _side_fragments(context)
    if _is_today_page(request):
        response += render("_day_log.html", oob=True, **context)
    return fragment_or_redirect(request, response)


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


@router.post("/entries/restart")
def restart_entry(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Restart the clock after a break."""
    session.restart_clock(conn, now=now)
    return fragment_or_redirect(request, _log_fragments(conn, now=now))


@router.api_route("/entries/{entry_id}", methods=["PATCH", "POST"])
def amend_entry(
    request: Request,
    entry_id: int,
    started_at: str | None = Form(None),
    ended_at: str | None = Form(None),
    description: str | None = Form(None),
    speed: str | None = Form(None),
    log_group: str | None = Form(None),
    notes: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Correct a line of the log, and redraw the day it belongs to.

    Registered for POST as well as PATCH, like the exercise edit: HTML forms
    send neither PATCH nor anything else HTMX might prefer.
    """
    entry = repo.get_entry(conn, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no entry with that id")
    try:
        amended = session.amend_entry(
            conn,
            entry_id=entry_id,
            started_at=_at(started_at, entry.started_at),
            ended_at=_at(ended_at, entry.ended_at),
            description=description,
            speed=speed,
            log_group=log_group,
            notes=notes,
        )
    except session.EntryRunning:
        raise HTTPException(
            status_code=409, detail="that entry is the running clock"
        ) from None
    except ValueError as unreadable:
        raise HTTPException(status_code=400, detail=str(unreadable)) from None

    # Still editing afterwards: the line below this one may be wrong too.
    day = practice_day_for(amended.started_at)
    return fragment_or_redirect(request, _amended_day(conn, day=day, now=now))


@router.api_route("/entries/{entry_id}", methods=["DELETE"])
@router.post("/entries/{entry_id}/delete")
def remove_entry(
    request: Request,
    entry_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> Response:
    """Take a line out of the log, and redraw the day without it.

    HTMX sends the `DELETE`; the `/delete` path is the same handler for a
    plain form, which can only manage GET and POST.
    """
    entry = repo.get_entry(conn, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no entry with that id")
    try:
        session.delete_entry(conn, entry_id=entry_id)
    except session.EntryRunning:
        raise HTTPException(
            status_code=409, detail="that entry is the running clock"
        ) from None
    return fragment_or_redirect(
        request, _amended_day(conn, day=practice_day_for(entry.started_at), now=now)
    )


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


def _amended_day(conn: sqlite3.Connection, *, day: date, now: datetime) -> str:
    """The day a correction landed on, still open for the next one."""
    if day == practice_day_for(now):
        return _log_fragments(conn, now=now, editing=True)
    return render(
        "_day_block.html", **views.day_context(conn, now=now, day=day, editing=True)
    )


def _day_view(
    request: Request,
    conn: sqlite3.Connection,
    *,
    day: date,
    now: datetime,
    editing: bool,
) -> HTMLResponse:
    """One day as a fragment for HTMX, and as a page for a plain browser."""
    if repo.get_day(conn, day) is None:
        raise HTTPException(status_code=404, detail=f"nothing logged on {day}")
    context = views.day_context(conn, now=now, day=day, editing=editing)
    if not is_htmx(request):
        return HTMLResponse(render("day.html", **context))
    fragment = "_day_log.html" if context["is_today"] else "_day_block.html"
    return HTMLResponse(render(fragment, **context))


def _at(written: str | None, current: datetime | None) -> datetime | None:
    """`22:46` on the date the entry already had, so midnight is not crossed.

    An entry keeps the day it happened on: only the time of day is editable,
    and an entry that ran to 00:20 keeps that end on the following date.
    """
    if written is None or current is None:
        return None
    try:
        return datetime.combine(current.date(), time.fromisoformat(written.strip()))
    except ValueError:
        raise ValueError(f"cannot read the time {written!r}") from None


def _log_fragments(
    conn: sqlite3.Connection, *, now: datetime, editing: bool = False
) -> str:
    """The log itself, with the totals and the clock riding behind it."""
    context = {**views.today_context(conn, now=now), "editing": editing}
    return render("_day_log.html", **context) + _side_fragments(context)


def _side_fragments(context: dict) -> str:
    """The rest of what a write changes, as out-of-band swaps.

    Not the log: whatever was clicked is already targeting one of these
    sections, and the same id twice in one response is a fight over the swap.
    """
    return render("_day_totals.html", oob=True, **context) + render(
        "_clock.html", oob=True, **context
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


def _is_today_page(request: Request) -> bool:
    """Whether request came from today page (contains day-log element)."""
    referer = request.headers.get("referer", "")
    return "/modules/" not in referer
