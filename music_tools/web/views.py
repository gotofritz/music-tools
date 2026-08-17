"""What each page needs, gathered in one place.

The routes are meant to be a line or two over `domain/`; the reading a page
does — the nav, the clock, the day block, the queue — is here so that a route
and the fragment it re-renders after a write cannot disagree about it.
"""

import sqlite3
from datetime import date, datetime
from typing import Any

from music_tools.db import repository as repo
from music_tools.domain import media
from music_tools.domain.models import Module, PracticeEntry
from music_tools.domain.session import (
    current_entry,
    day_summary,
    practice_day_for,
    recent_days,
)

#: How many finished days a page of history holds. Small on purpose: the
#: button is there for the rare look backwards, not for scrolling a year.
PAGE_OF_DAYS = 5


def running_entry(conn: sqlite3.Connection, *, now: datetime) -> PracticeEntry | None:
    """What is being practised right now, if anything.

    An entry left running from an earlier day is not it: that is time nobody
    attributed, and the next start drops it rather than closing it at an
    invented moment.
    """
    return current_entry(conn, now=now)


def chrome(conn: sqlite3.Connection, *, now: datetime) -> dict[str, Any]:
    """What every page carries: the module nav, and what is being played.

    The material comes with it, because the card the running entry draws is
    what makes the exercise's media visible at the moment it is wanted.
    """
    running = running_entry(conn, now=now)
    exercise = (
        repo.get_exercise(conn, running.exercise_id)
        if running is not None and running.exercise_id is not None
        else None
    )
    return {
        "now": now,
        "today": practice_day_for(now),
        "modules": repo.list_modules(conn),
        "running": running,
        "running_exercise": exercise,
        "running_media": (
            media.exercise_media(conn, exercise_id=exercise.id)
            if exercise is not None
            else []
        ),
    }


def today_context(conn: sqlite3.Connection, *, now: datetime) -> dict[str, Any]:
    """Today's block and totals, and the days behind it — the whole of `GET /`."""
    today = practice_day_for(now)
    return {
        **chrome(conn, now=now),
        "day": today,
        "summary": day_summary(conn, day=today, now=now),
        "live": now,
        "editing": False,
        "modules_by_id": modules_by_id(conn),
        **history_context(conn, now=now, before=today),
    }


def day_context(
    conn: sqlite3.Connection, *, now: datetime, day: date, editing: bool
) -> dict[str, Any]:
    """One day on its own — today's log, or a finished block, in either mode."""
    is_today = day == practice_day_for(now)
    return {
        **chrome(conn, now=now),
        "day": day,
        "edit_day": day,
        "is_today": is_today,
        "editing": editing,
        "live": now if is_today else None,
        "summary": day_summary(conn, day=day, now=now),
    }


def history_context(
    conn: sqlite3.Connection, *, now: datetime, before: date
) -> dict[str, Any]:
    """One page of finished days, and the date the next page starts from.

    One row more than the page is read, and thrown away: it is the cheapest
    way to know whether there is anything left to ask for, which is all the
    "load more" button needs.
    """
    days = recent_days(conn, before=before, limit=PAGE_OF_DAYS + 1, now=now)
    return {
        "history": days[:PAGE_OF_DAYS],
        "more_before": days[PAGE_OF_DAYS - 1].day if len(days) > PAGE_OF_DAYS else None,
    }


def modules_by_id(conn: sqlite3.Connection) -> dict[int, Module]:
    """Enough to name the module a due row belongs to, without a join."""
    return {
        module.id: module for module in repo.list_modules(conn, include_archived=True)
    }
