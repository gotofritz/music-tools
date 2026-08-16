"""What each page needs, gathered in one place.

The routes are meant to be a line or two over `domain/`; the reading a page
does — the nav, the clock, the day block, the queue — is here so that a route
and the fragment it re-renders after a write cannot disagree about it.
"""

import sqlite3
from datetime import date, datetime
from typing import Any

from music_tools.db import repository as repo
from music_tools.domain.models import Module, PracticeEntry
from music_tools.domain.session import day_summary, practice_day_for, recent_days

#: How many finished days a page of history holds. Small on purpose: the
#: button is there for the rare look backwards, not for scrolling a year.
PAGE_OF_DAYS = 5


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
    """Today's block and totals, and the days behind it — the whole of `GET /`."""
    today = practice_day_for(now)
    day = repo.get_day(conn, today)
    return {
        **chrome(conn, now=now),
        "day": today,
        "day_started": day is not None,
        "summary": day_summary(conn, day=today, now=now),
        "live": now,
        "modules_by_id": modules_by_id(conn),
        **history_context(conn, now=now, before=today),
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
