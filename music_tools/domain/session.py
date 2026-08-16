"""Practising: starting a day, marking an exercise done, and the day totals.

`mark_done` is the knot the whole app pulls on. `doneExercise_` in bass.gs did
five things at once — bump the count, stamp today, compute the next due date,
write the log line, re-sort — and the port keeps the first four in one
transaction. The re-sort was `ORDER BY next_due` and lives in the repository.

The clock is always an argument. Nothing in this module calls
`datetime.now()`; the CLI is the only place that does.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta

from music_tools.db import repository as repo
from music_tools.db.connection import transaction
from music_tools.domain.models import (
    DaySummary,
    DoneResult,
    GroupTotal,
    LogResult,
    PracticeDay,
    PracticeEntry,
    RestartResult,
)
from music_tools.domain.scheduling import Algorithm, next_due
from music_tools.domain.tempo import parse_tempo

#: Practice past midnight belongs to the evening it started in. Declared but
#: never used in Code.gs; adopted here.
END_OF_DAY_HOUR = 4


class UnknownExercise(LookupError):
    """No exercise with that id."""


class UnknownEntry(LookupError):
    """No day-log entry with that id."""


class EntryRunning(RuntimeError):
    """The entry is the clock, and the clock is not edited by hand."""


def practice_day_for(now: datetime) -> date:
    """Which practice day an instant falls in, at the 4am boundary."""
    return (now - timedelta(hours=END_OF_DAY_HOUR)).date()


def start_day(
    conn: sqlite3.Connection, *, now: datetime, notes: str | None = None
) -> PracticeDay:
    """`New Day`: open the day `now` falls in, and start the clock running."""
    with transaction(conn):
        return _start_day(conn, now=now, notes=notes)


def restart_clock(conn: sqlite3.Connection, *, now: datetime) -> RestartResult:
    """Start again from now, after a break.

    Entries normally follow on from each other — the clock runs from the last
    thing you finished, which is what makes a session tile end to end. It is
    wrong after a break: the coffee, the phone call and the walk round the
    block would all be logged against whatever you played next. `restart_clock`
    moves the running entry's start to `now` — the `FROM` stamp, restamped — so
    the gap is never attributed to anything, the same way an entry left running
    from an earlier day is never attributed.
    """
    with transaction(conn):
        day = _start_day(conn, now=now)
        dropped = 0
        running = repo.running_entry(conn, day_id=day.id)
        if running is None:  # pragma: no cover - _start_day just opened one
            opened = repo.create_entry(conn, day_id=day.id, started_at=now)
        else:
            dropped = max(0, int((now - running.started_at).total_seconds()))
            opened = repo.update_entry(conn, running.id, started_at=now)
        return RestartResult(opened=opened, dropped_seconds=dropped)


def mark_done(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    algorithm: Algorithm,
    now: datetime,
    rng: random.Random,
    notes: str | None = None,
) -> DoneResult:
    """Practised it: move the schedule and tick the day log over."""
    with transaction(conn):
        exercise = repo.get_exercise(conn, exercise_id)
        if exercise is None:
            raise UnknownExercise(exercise_id)
        module = repo.get_module(conn, exercise.module_id)

        day = _start_day(conn, now=now)
        running = repo.running_entry(conn, day_id=day.id)
        if running is None:  # pragma: no cover - _start_day just opened one
            running = repo.create_entry(conn, day_id=day.id, started_at=now)

        tempo = parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)
        count = exercise.practiced_count + 1
        # HOLD's scan skips the row being scheduled and ROTATE's does not; the
        # sheet's two scans disagree on exactly this.
        dues = repo.module_dues(
            conn,
            module_id=exercise.module_id,
            excluding=exercise_id if algorithm is Algorithm.HOLD else None,
        )
        due = next_due(
            algorithm=algorithm,
            count=count,
            last_practiced=now.date(),
            ratio=tempo.ratio,
            module_dues=dues,
            rng=rng,
            current_due=exercise.next_due,
        )

        updated = repo.update_exercise(
            conn,
            exercise_id,
            practiced_count=count,
            last_practiced=now.date(),
            next_due=due,
        )
        closed = repo.close_entry(
            conn,
            running.id,
            ended_at=now,
            exercise_id=exercise.id,
            description=exercise.name,
            speed=exercise.speed,
            bpm=tempo.bpm,
            log_group=module.log_group if module else None,
            notes=notes if notes is not None else exercise.notes,
        )
        opened = repo.create_entry(conn, day_id=day.id, started_at=now)
        return DoneResult(exercise=updated, closed=closed, opened=opened)


def log_entry(
    conn: sqlite3.Connection,
    *,
    description: str,
    now: datetime,
    log_group: str | None = None,
    speed: str | None = None,
    notes: str | None = None,
) -> LogResult:
    """Log something that is not in the catalogue: a warm-up, a jam, a lesson.

    `mark_done` without the schedule half — the running entry is closed with
    what was played written into it, and the next one opens at the same
    instant, so the session still tiles end to end.
    """
    with transaction(conn):
        day = _start_day(conn, now=now)
        running = repo.running_entry(conn, day_id=day.id)
        if running is None:  # pragma: no cover - _start_day just opened one
            running = repo.create_entry(conn, day_id=day.id, started_at=now)
        closed = repo.close_entry(
            conn,
            running.id,
            ended_at=now,
            description=description,
            log_group=log_group,
            speed=speed,
            notes=notes,
        )
        opened = repo.create_entry(conn, day_id=day.id, started_at=now)
        return LogResult(closed=closed, opened=opened)


def stop_clock(
    conn: sqlite3.Connection, *, entry_id: int, now: datetime
) -> PracticeEntry | None:
    """Stop the clock: the session is over, and nothing follows this entry.

    An entry that already says what was played is closed at `now`. The running
    one never does — `mark_done` writes the description as it closes a line,
    not as it opens the next — so stopping discards it. That is the same rule
    `restart_clock` follows: time nobody attributed is not practice time, and
    the app will not invent an attribution for it.
    """
    with transaction(conn):
        entry = repo.get_entry(conn, entry_id)
        if entry is None:
            raise UnknownEntry(entry_id)
        if entry.ended_at is not None:
            return entry
        if entry.description:
            return repo.close_entry(conn, entry.id, ended_at=now)
        repo.delete_entry(conn, entry.id)
        return None


def entry_duration(entry: PracticeEntry, *, now: datetime | None = None) -> int:
    """How long an entry lasted, in seconds.

    An entry that starts at 23:50 and ends at 00:20 crossed midnight and lasted
    30 minutes, not minus 23 hours. A running entry counts up to `now`, and to
    nothing at all when `now` is not the day it belongs to.
    """
    ended = entry.ended_at if entry.ended_at is not None else now
    if ended is None:
        return 0
    if ended < entry.started_at:
        ended += timedelta(days=1)
    return int((ended - entry.started_at).total_seconds())


def day_summary(
    conn: sqlite3.Connection, *, day: date, now: datetime | None = None
) -> DaySummary:
    """A day block with its per-log-group subtotals and its total.

    Subtotals are grouped, not summed over a range of rows, so the groups need
    not be contiguous — which is what `compressRowsToRanges_` was working
    around. Time not yet attributed to a group (the entry running right now)
    counts towards the total but has no subtotal of its own.
    """
    record = repo.get_day(conn, day)
    if record is None:
        return DaySummary(day=day)

    live = now if now is not None and practice_day_for(now) == day else None
    entries = repo.entries_for_day(conn, record.id)

    seconds_by_group: dict[str, int] = {}
    total = 0
    for entry in entries:
        seconds = entry_duration(entry, now=live)
        total += seconds
        if entry.log_group:
            seconds_by_group[entry.log_group] = (
                seconds_by_group.get(entry.log_group, 0) + seconds
            )

    return DaySummary(
        day=day,
        entries=entries,
        groups=[
            GroupTotal(log_group=group, seconds=seconds)
            for group, seconds in seconds_by_group.items()
        ],
        total_seconds=total,
    )


def amend_entry(
    conn: sqlite3.Connection,
    *,
    entry_id: int,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    description: str | None = None,
    speed: str | None = None,
    log_group: str | None = None,
    notes: str | None = None,
) -> PracticeEntry:
    """Correct a line of the log. Only what is passed is rewritten.

    The log is a record, and the app writes it as practice happens — but the
    record can be wrong: a clock left running through supper, a name typed in
    a hurry. Correcting it is a deliberate act, and narrow by design. An entry
    keeps the day it happened on, nothing is deleted, and the running entry is
    refused: that one is the clock, written by `mark_done` and `stop_clock`,
    and hand-editing it would make the two disagree.

    Times are passed whole, so an entry that crossed midnight keeps its dates.
    Nothing re-tiles: closing a gap in the middle of a session is the caller's
    business, and the day's total is the sum of its entries either way.
    """
    with transaction(conn):
        entry = repo.get_entry(conn, entry_id)
        if entry is None:
            raise UnknownEntry(entry_id)
        if entry.ended_at is None:
            raise EntryRunning(entry_id)
        fields = {
            "started_at": started_at,
            "ended_at": ended_at,
            "description": description,
            "speed": speed,
            "log_group": log_group,
            "notes": notes,
        }
        given = {name: value for name, value in fields.items() if value is not None}
        return repo.update_entry(conn, entry.id, **given) if given else entry


def delete_entry(conn: sqlite3.Connection, *, entry_id: int) -> None:
    """Take a line out of the log altogether.

    For the block that should never have been written down — a session logged
    twice, or against the wrong thing entirely. Correcting the line is the
    usual move (`amend_entry`); this is for when there is nothing to correct.
    The running entry is refused for the same reason it cannot be amended:
    that one is the clock, and `stop_clock` is what drops it.
    """
    with transaction(conn):
        entry = repo.get_entry(conn, entry_id)
        if entry is None:
            raise UnknownEntry(entry_id)
        if entry.ended_at is None:
            raise EntryRunning(entry_id)
        repo.delete_entry(conn, entry.id)


def recent_days(
    conn: sqlite3.Connection, *, before: date, limit: int, now: datetime | None = None
) -> list[DaySummary]:
    """A page of finished days, most recent first, each with its own totals.

    `before` is exclusive, so passing the last day of one page reads the next:
    that is the whole of the pagination, and it needs no offset and no count.
    """
    return [
        day_summary(conn, day=record.day, now=now)
        for record in repo.days_before(conn, before=before, limit=limit)
    ]


def format_duration(seconds: int) -> str:
    """`00:53`, the way the sheet's TIME column read."""
    minutes = seconds // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_due(due: date | None) -> str:
    """The due date as the sheet showed it, or an em dash for undated rows."""
    return due.isoformat() if due else "—"


def format_when(due: date | None, today: date) -> str:
    """`3 days overdue`, `due today`, `in 30 days`."""
    if due is None:
        return "no due date"
    days = (due - today).days
    if days == 0:
        return "due today"
    if days < 0:
        return f"{-days} day{'s' if days != -1 else ''} overdue"
    return f"in {days} day{'s' if days != 1 else ''}"


def _start_day(
    conn: sqlite3.Connection, *, now: datetime, notes: str | None = None
) -> PracticeDay:
    """The body of `start_day`, for callers already inside a transaction."""
    today = practice_day_for(now)
    day = repo.get_day(conn, today) or repo.create_day(conn, day=today, notes=notes)
    for stale in repo.running_entries_before(conn, day_id=day.id):
        # The dangling FROM the sheet left behind: time that was never
        # attributed, and cannot be closed at an invented moment.
        repo.delete_entry(conn, stale.id)
    if repo.running_entry(conn, day_id=day.id) is None:
        repo.create_entry(conn, day_id=day.id, started_at=now)
    return day
