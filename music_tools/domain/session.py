"""Practising: starting an exercise, finishing it, and the day totals.

The log used to be a clock. `doneExercise_` in bass.gs closed one entry and
opened the next, so a session tiled end to end and `start` / "stop the clock"
existed to keep the tiling honest across a break. Phase 4 of
`docs/plans/00-practice-app.md` drops all of that:

- **start** opens an entry, immediately visible in the day log with the
  exercise's material on it.
- **done** closes that entry and moves the schedule on.
- **discard** takes a false start out again.

Two rules survive the change. **One entry runs at a time**: starting the next
closes the one before it at that instant — it was attributed when it was
started, so closing it is honest — and closing it says `done` for it, on the
normal interval: the sheet's chained log is back, because nothing else is ever
going to move that exercise's schedule. Only **discard** closes a line without
scheduling it. And
**time nobody attributed is not practice time**: the gaps between entries are
gaps, nothing re-tiles, and an entry left running from an earlier day is
discarded rather than closed at an invented moment.

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
    PracticeDay,
    PracticeEntry,
    StartResult,
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
    """The entry is the one being practised; `done` and `discard` move it."""


class EntryClosed(RuntimeError):
    """The entry is already finished, so there is nothing to close or drop."""


def practice_day_for(now: datetime) -> date:
    """Which practice day an instant falls in, at the 4am boundary."""
    return (now - timedelta(hours=END_OF_DAY_HOUR)).date()


def start_day(
    conn: sqlite3.Connection, *, now: datetime, notes: str | None = None
) -> PracticeDay:
    """`New Day`: open the day `now` falls in. No entry, and no clock.

    Starting an exercise opens the day it falls in anyway, so this is only for
    a day that wants notes on it before anything is played.
    """
    with transaction(conn):
        return _start_day(conn, now=now, notes=notes)


def current_entry(conn: sqlite3.Connection, *, now: datetime) -> PracticeEntry | None:
    """What is being practised right now, if anything.

    An entry left running from an earlier day is not it: that is time nobody
    attributed, and the next start discards it.
    """
    return _running_for(conn, now=now)


def start_exercise(
    conn: sqlite3.Connection, *, exercise_id: int, now: datetime, rng: random.Random
) -> StartResult:
    """Playing this now: open an entry for it, and show it in the day log.

    The line is snapshotted here rather than when it closes, because this is
    when it becomes visible: what it says is what the exercise was called when
    you sat down to it, whatever happens to the row afterwards. This exercise's
    own schedule is not touched — `finish_entry` is what moves that — but the
    entry this start closes is scheduled as though `done` had been said for it,
    on the normal interval, which is why the rng is wanted here.

    Starting the exercise that is already running is nothing at all: the line
    keeps the time it really began at. Every row on a module page carries a
    start button, so the click is as likely to mean "this is the one" as it is
    to mean "again from here", and restarting would lose the minutes played.
    """
    with transaction(conn):
        exercise = repo.get_exercise(conn, exercise_id)
        if exercise is None:
            raise UnknownExercise(exercise_id)
        running = _running_for(conn, now=now)
        if running is not None and running.exercise_id == exercise_id:
            return StartResult(entry=running, closed=None)
        module = repo.get_module(conn, exercise.module_id)
        tempo = parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)

        day = _start_day(conn, now=now)
        closed = _close_running(conn, day_id=day.id, now=now, rng=rng)
        entry = repo.create_entry(
            conn,
            day_id=day.id,
            started_at=now,
            exercise_id=exercise.id,
            description=exercise.name,
            speed=exercise.speed,
            bpm=tempo.bpm,
            log_group=module.log_group if module else None,
            notes=exercise.notes,
        )
        return StartResult(entry=entry, closed=closed)


def start_ad_hoc(
    conn: sqlite3.Connection,
    *,
    description: str,
    now: datetime,
    rng: random.Random,
    log_group: str | None = None,
    speed: str | None = None,
    notes: str | None = None,
) -> StartResult:
    """Start something the catalogue does not know about: a warm-up, a jam.

    `start_exercise` with a description typed in instead of an exercise to
    snapshot, so there is nothing to schedule when it finishes. The entry it
    closes is scheduled, though, exactly as `start_exercise` schedules it.
    """
    with transaction(conn):
        day = _start_day(conn, now=now)
        closed = _close_running(conn, day_id=day.id, now=now, rng=rng)
        entry = repo.create_entry(
            conn,
            day_id=day.id,
            started_at=now,
            description=description,
            log_group=log_group,
            speed=speed,
            notes=notes,
        )
        return StartResult(entry=entry, closed=closed)


def finish_entry(
    conn: sqlite3.Connection,
    *,
    entry_id: int,
    algorithm: Algorithm,
    now: datetime,
    rng: random.Random,
    notes: str | None = None,
) -> DoneResult:
    """Done with it: close the entry, and move the schedule it belongs to.

    The snapshot the start took is left as it was; only the end — and a note,
    if one is given — is written now. An ad-hoc entry has no exercise, so
    there is nothing to schedule and the line is simply closed.
    """
    with transaction(conn):
        entry = repo.get_entry(conn, entry_id)
        if entry is None:
            raise UnknownEntry(entry_id)
        if entry.ended_at is not None:
            raise EntryClosed(entry_id)
        return _finish(conn, entry, algorithm=algorithm, now=now, rng=rng, notes=notes)


def _finish(
    conn: sqlite3.Connection,
    entry: PracticeEntry,
    *,
    algorithm: Algorithm,
    now: datetime,
    rng: random.Random,
    notes: str | None = None,
) -> DoneResult:
    """Close a running entry and move its schedule, inside a transaction.

    The body `finish_entry` and `_close_running` share: `done` said out loud,
    and `done` said by starting the next thing.
    """
    exercise = (
        repo.get_exercise(conn, entry.exercise_id)
        if entry.exercise_id is not None
        else None
    )
    closed = repo.close_entry(
        conn,
        entry.id,
        ended_at=now,
        **({"notes": notes} if notes is not None else {}),
    )
    if exercise is None:
        return DoneResult(exercise=None, closed=closed)

    tempo = parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)
    count = exercise.practiced_count + 1
    # HOLD's scan skips the row being scheduled and ROTATE's does not; the
    # sheet's two scans disagree on exactly this.
    dues = repo.module_dues(
        conn,
        module_id=exercise.module_id,
        excluding=exercise.id if algorithm is Algorithm.HOLD else None,
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
        exercise.id,
        practiced_count=count,
        last_practiced=now.date(),
        next_due=due,
    )
    return DoneResult(exercise=updated, closed=closed)


def stop_exercise(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    algorithm: Algorithm,
    now: datetime,
    rng: random.Random,
    notes: str | None = None,
) -> DoneResult | None:
    """`finish_entry` addressed to an exercise rather than to a line of the log.

    Every row carries a stop button, so a stop while something else is running
    is a click on the wrong row: nothing happens. With **nothing** running it
    is the start that was never clicked — the player went on playing after
    stopping the last thing — so the line is written backwards from the stop:
    it opens a microsecond after the last line of the day closed, and closes
    now. The gap since the last line is what was practised, so attributing it
    is honest; inventing one before there is a line to follow on from is not,
    and a day with nothing logged in it yet writes nothing.
    """
    running = _running_for(conn, now=now)
    if running is not None:
        if running.exercise_id != exercise_id:
            return None
        return finish_entry(
            conn,
            entry_id=running.id,
            algorithm=algorithm,
            now=now,
            rng=rng,
            notes=notes,
        )
    return _backfill(
        conn,
        exercise_id=exercise_id,
        algorithm=algorithm,
        now=now,
        rng=rng,
        notes=notes,
    )


def _backfill(
    conn: sqlite3.Connection,
    *,
    exercise_id: int,
    algorithm: Algorithm,
    now: datetime,
    rng: random.Random,
    notes: str | None = None,
) -> DoneResult | None:
    """The start that was never clicked: a line from the last close to now.

    Snapshotted exactly as `start_exercise` snapshots it, then closed and
    scheduled through the same `_finish` a deliberate stop goes through. The
    day is never opened here and no earlier day is tidied: without a line to
    follow on from there is no stretch to attribute, so there is nothing to
    write.
    """
    with transaction(conn):
        exercise = repo.get_exercise(conn, exercise_id)
        if exercise is None:
            raise UnknownExercise(exercise_id)
        day = repo.get_day(conn, practice_day_for(now))
        if day is None:
            return None
        last_end = _last_end(conn, day_id=day.id)
        if last_end is None or last_end >= now:
            return None

        module = repo.get_module(conn, exercise.module_id)
        tempo = parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)
        entry = repo.create_entry(
            conn,
            day_id=day.id,
            started_at=last_end + timedelta(microseconds=1),
            exercise_id=exercise.id,
            description=exercise.name,
            speed=exercise.speed,
            bpm=tempo.bpm,
            log_group=module.log_group if module else None,
            notes=exercise.notes,
        )
        return _finish(conn, entry, algorithm=algorithm, now=now, rng=rng, notes=notes)


def _last_end(conn: sqlite3.Connection, *, day_id: int) -> datetime | None:
    """When the last line of the day closed, or None on an empty day."""
    ends = [
        entry.ended_at
        for entry in repo.entries_for_day(conn, day_id)
        if entry.ended_at is not None
    ]
    return max(ends) if ends else None


def discard_entry(conn: sqlite3.Connection, *, entry_id: int) -> None:
    """A false start: the entry goes, and no time is logged against it.

    The same rule as the entry left running from an earlier day — time nobody
    attributed is not practice time. A finished line is refused: correcting or
    removing one of those is `amend_entry` and `delete_entry`.
    """
    with transaction(conn):
        entry = repo.get_entry(conn, entry_id)
        if entry is None:
            raise UnknownEntry(entry_id)
        if entry.ended_at is not None:
            raise EntryClosed(entry_id)
        repo.delete_entry(conn, entry.id)


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
    record can be wrong: a line left running through supper, a name typed in
    a hurry. Correcting it is a deliberate act, and narrow by design. An entry
    keeps the day it happened on, nothing is deleted, and the entry being
    practised is refused: `finish_entry` and `discard_entry` are what move that
    one, and hand-editing it would put the two out of step.

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
    The entry being practised is refused for the same reason it cannot be
    amended: `discard_entry` is what drops that one.
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
    return day


def _running_for(conn: sqlite3.Connection, *, now: datetime) -> PracticeEntry | None:
    """`current_entry`, for callers already holding a transaction open."""
    day = repo.get_day(conn, practice_day_for(now))
    return repo.running_entry(conn, day_id=day.id) if day else None


def _close_running(
    conn: sqlite3.Connection, *, day_id: int, now: datetime, rng: random.Random
) -> PracticeEntry | None:
    """One entry at a time: starting the next closes whatever was running.

    It was attributed when it was started, so closing it at this instant is
    honest, and it is scheduled here too, on the normal interval — the sheet
    chained its log the same way. Nothing else would ever move that exercise:
    the player has gone on to the next thing. A choice other than `normal` is
    what `finish_entry` is for, and a line that should not be scheduled at all
    is `discard_entry`.
    """
    running = repo.running_entry(conn, day_id=day_id)
    if running is None:
        return None
    return _finish(conn, running, algorithm=Algorithm.NORMAL, now=now, rng=rng).closed
