"""The day: what is due, one click to mark it done, and the running log."""

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from music_tools.domain import session
from music_tools.web import views
from music_tools.web.deps import fragment_or_redirect, get_conn, get_now, render

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
    """Start the day, and set the clock running. Twice is once."""
    session.start_day(conn, now=now)
    context = views.today_context(conn, now=now)
    return fragment_or_redirect(
        request,
        render("_day_log.html", **context)
        + render("_day_totals.html", oob=True, **context),
    )
