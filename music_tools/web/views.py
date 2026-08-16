"""What each page needs, gathered in one place.

The routes are meant to be a line or two over `domain/`; the reading a page
does — the nav, the clock, the day block, the queue — is here so that a route
and the fragment it re-renders after a write cannot disagree about it.
"""

import sqlite3
from datetime import datetime
from typing import Any

from music_tools.db import repository as repo
from music_tools.domain.models import Module, PracticeEntry
from music_tools.domain.session import day_summary, practice_day_for


def running_entry(conn: sqlite3.Connection, *, now: datetime) -> PracticeEntry | None:
    """The clock, if it is running today.

    An entry left running from an earlier day is not the clock: it is time
    nobody attributed, and `start_day` drops it rather than closing it at an
    invented moment.
    """
    day = repo.get_day(conn, practice_day_for(now))
    return repo.running_entry(conn, day_id=day.id) if day else None


def chrome(conn: sqlite3.Connection, *, now: datetime) -> dict[str, Any]:
    """What every page carries: the module nav, and the running clock."""
    return {
        "now": now,
        "today": practice_day_for(now),
        "modules": repo.list_modules(conn),
        "running": running_entry(conn, now=now),
    }


def today_context(conn: sqlite3.Connection, *, now: datetime) -> dict[str, Any]:
    """The day block, its totals, and what is due — the whole of `GET /`."""
    today = practice_day_for(now)
    day = repo.get_day(conn, today)
    due = repo.exercises_due(conn, on=today)
    return {
        **chrome(conn, now=now),
        "day": today,
        "day_started": day is not None,
        "summary": day_summary(conn, day=today, now=now),
        "live": now,
        "due": due,
        "modules_by_id": modules_by_id(conn),
    }


def modules_by_id(conn: sqlite3.Connection) -> dict[int, Module]:
    """Enough to name the module a due row belongs to, without a join."""
    return {
        module.id: module
        for module in repo.list_modules(conn, include_archived=True)
    }
