"""`practice` — the terminal front end to the practice domain.

Thin on purpose: every command is a few lines over `domain/` and `db/`. It
exists to prove the domain before there is any HTML, and it stays useful
afterwards.

This module is the only place in the codebase that reads the clock or builds a
`random.Random`; everything below takes both as arguments.
"""

import difflib
import random
import sqlite3
from datetime import date, datetime
from pathlib import Path

import click

from music_tools.db import repository as repo
from music_tools.db.connection import default_db_path, open_db
from music_tools.db.migrate import migrate
from music_tools.domain.models import Exercise, PracticeEntry
from music_tools.domain.scheduling import Algorithm
from music_tools.domain.session import (
    day_summary,
    entry_duration,
    format_duration,
    mark_done,
    practice_day_for,
    start_day,
)
from music_tools.domain.tempo import format_tempo, parse_tempo
from music_tools.importer.sheets import import_sheets


@click.group()
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Database file. Defaults to $MUSIC_TOOLS_DB, or ~/.local/share.",
)
@click.pass_context
def practice(ctx: click.Context, db_path: Path | None) -> None:
    """Track bass practice: what is due, what was done, and when it comes back."""
    ctx.obj = db_path or default_db_path()


@practice.group()
def module() -> None:
    """Practice areas — one per sheet, back when it was a spreadsheet."""


@module.command("add")
@click.argument("name")
@click.option("--log-group", required=True, help="TECHNIQUE, REPERTOIRE, ...")
@click.option("--instrument", default="bass", show_default=True)
@click.pass_context
def module_add(ctx: click.Context, name: str, log_group: str, instrument: str) -> None:
    """Add a practice area."""
    conn = _connect(ctx)
    if repo.find_module(conn, name):
        raise click.ClickException(f"there is already a module called {name}")
    created = repo.create_module(
        conn, name=name, log_group=log_group, instrument=instrument
    )
    click.echo(f"{created.name} ({created.log_group}) added")


@module.command("list")
@click.pass_context
def module_list(ctx: click.Context) -> None:
    """List the practice areas."""
    conn = _connect(ctx)
    modules = repo.list_modules(conn)
    if not modules:
        click.echo("Nothing here yet — add a module first.")
        return
    for found in modules:
        count = len(repo.exercises_due(conn, module_id=found.id))
        click.echo(f"{found.name:<12} {found.log_group:<12} {count} exercises")


@practice.command("add")
@click.argument("module_name", metavar="MODULE")
@click.argument("name")
@click.option("--speed", help='As typed: "80%", "66", "66/1", "123/0.5".')
@click.option("--target-bpm", type=float, help="The tempo this is aiming at.")
@click.option("--style", help="The row's own tag: NEOSOUL, RNB, DANCE.")
@click.option("--due", "next_due", help="ISO date it is next due.")
@click.option("--notes")
@click.pass_context
def add_exercise(
    ctx: click.Context,
    module_name: str,
    name: str,
    speed: str | None,
    target_bpm: float | None,
    style: str | None,
    next_due: str | None,
    notes: str | None,
) -> None:
    """Add an exercise to a module."""
    conn = _connect(ctx)
    found = repo.find_module(conn, module_name)
    if found is None:
        raise click.ClickException(f"no module called {module_name}")
    exercise = repo.create_exercise(
        conn,
        module_id=found.id,
        name=name,
        speed=speed,
        target_bpm=target_bpm,
        style=style,
        next_due=_parse_day(next_due) if next_due else None,
        notes=notes,
    )
    click.echo(f"{found.name}/{exercise.name} added, {_tempo(exercise)}")


@practice.command("speed")
@click.argument("exercise")
@click.argument("speed")
@click.option("--target-bpm", type=float, help="Also retune what it is aiming at.")
@click.pass_context
def set_speed(
    ctx: click.Context, exercise: str, speed: str, target_bpm: float | None
) -> None:
    """Set the speed an exercise is currently practised at."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    fields: dict[str, object] = {"speed": speed}
    if target_bpm is not None:
        fields["target_bpm"] = target_bpm
    updated = repo.update_exercise(conn, found.id, **fields)
    click.echo(f"{updated.name} now at {_tempo(updated)}")


@practice.command("next")
@click.argument("module_name", metavar="[MODULE]", required=False)
@click.option("--limit", type=int, default=10, show_default=True)
@click.pass_context
def next_up(ctx: click.Context, module_name: str | None, limit: int) -> None:
    """What is due, oldest first."""
    conn = _connect(ctx)
    module_id = None
    if module_name:
        found = repo.find_module(conn, module_name)
        if found is None:
            raise click.ClickException(f"no module called {module_name}")
        module_id = found.id

    exercises = repo.exercises_due(conn, module_id=module_id)
    if not exercises:
        click.echo("Nothing to practise — no exercises here yet.")
        return

    today = practice_day_for(datetime.now())
    for exercise in exercises[:limit]:
        found = repo.get_module(conn, exercise.module_id)
        click.echo(
            f"{_due_column(exercise.next_due):<12}"
            f" {_when(exercise.next_due, today):<16}"
            f" {found.name if found else '?'}/{exercise.name:<24}"
            f" {_tempo(exercise):<20} x{exercise.practiced_count}"
        )


@practice.command("done")
@click.argument("exercise")
@click.option(
    "--short", "algorithm", flag_value=Algorithm.SHORT, help="Half the table."
)
@click.option(
    "--long", "algorithm", flag_value=Algorithm.LONG, help="One and a half times it."
)
@click.option(
    "--rotate",
    "algorithm",
    flag_value=Algorithm.ROTATE,
    help="To the back of the queue.",
)
@click.option(
    "--hold", "algorithm", flag_value=Algorithm.HOLD, help="Keep it at the front."
)
@click.option("--notes", help="A note for the log line.")
@click.pass_context
def done(
    ctx: click.Context, exercise: str, algorithm: str | None, notes: str | None
) -> None:
    """Mark an exercise practised: move the schedule and log the time."""
    conn = _connect(ctx)
    found = _resolve(conn, exercise)
    now = datetime.now()
    result = mark_done(
        conn,
        exercise_id=found.id,
        algorithm=Algorithm(algorithm) if algorithm else Algorithm.NORMAL,
        now=now,
        rng=random.Random(),
        notes=notes,
    )

    updated = result.exercise
    today = practice_day_for(now)
    click.echo(
        f"{updated.name} done — practised {updated.practiced_count} times,"
        f" next due {_due_column(updated.next_due)}"
        f" ({_when(updated.next_due, today)})"
    )
    entry = result.closed
    click.echo(
        f"logged {entry.started_at:%H:%M}-{now:%H:%M}"
        f"  {format_duration(int((now - entry.started_at).total_seconds()))}"
        f"  {entry.log_group or '-'}  {_tempo(updated)}"
    )


@practice.group()
def day() -> None:
    """The practice day."""


@day.command("new")
@click.pass_context
def day_new(ctx: click.Context) -> None:
    """Start a day and set the clock running."""
    conn = _connect(ctx)
    now = datetime.now()
    started = start_day(conn, now=now)
    click.echo(f"{started.day.isoformat()} started, clock running from {now:%H:%M}")


@practice.command("log")
@click.option("--day", "which", default="today", show_default=True, help="ISO date.")
@click.pass_context
def show_log(ctx: click.Context, which: str) -> None:
    """The day block, with its subtotals."""
    conn = _connect(ctx)
    now = datetime.now()
    summary = day_summary(conn, day=_parse_day(which, now=now), now=now)
    if not summary.entries:
        click.echo(f"Nothing logged for {summary.day.isoformat()}.")
        return

    click.echo(summary.day.isoformat())
    for entry in summary.entries:
        ended = f"{entry.ended_at:%H:%M}" if entry.ended_at else "  :  "
        running = "" if entry.ended_at else "  (running)"
        description = entry.description + (f" ({entry.notes})" if entry.notes else "")
        click.echo(
            f"  {entry.started_at:%H:%M}-{ended}"
            f"  {format_duration(_seconds(entry, now))}"
            f"  {description[:48]:<48}"
            f"  {entry.speed or '':<8} {entry.log_group or '':<12}{running}"
        )
    click.echo()
    for group in summary.groups:
        click.echo(f"  {group.log_group:<12} {format_duration(group.seconds)}")
    click.echo(f"  {'TOTAL':<12} {format_duration(summary.total_seconds)}")


@practice.command("import")
@click.option(
    "--modules",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Module sheet exports, one per practice area.",
)
@click.option(
    "--day-log",
    type=click.Path(exists=True, path_type=Path),
    help="The BASS day log export.",
)
@click.pass_context
def import_command(
    ctx: click.Context, modules: tuple[Path, ...], day_log: Path | None
) -> None:
    """Import the spreadsheet exports."""
    conn = _connect(ctx)
    report = import_sheets(conn, modules=list(modules), day_log=day_log)
    click.echo(
        "imported "
        + ", ".join(
            [
                _plural(report.modules_created, "module"),
                f"{_plural(report.exercises_created, 'exercise')}"
                f" ({report.exercises_updated} updated)",
                _plural(report.days_created, "day"),
                f"{_plural(report.entries_created, 'entry', 'entries')}"
                f" ({report.entries_updated} updated)",
            ]
        )
    )
    for problem in report.problems:
        click.echo(f"  ! {problem}", err=True)


# --- plumbing ---------------------------------------------------------------


def _connect(ctx: click.Context) -> sqlite3.Connection:
    """Open the database named on the command line, and migrate it."""
    conn = open_db(ctx.obj)
    migrate(conn)
    return conn


def _resolve(conn: sqlite3.Connection, token: str) -> Exercise:
    """`NAME`, or `MODULE/NAME` when a name lives in more than one module."""
    module_name, _, name = token.rpartition("/")
    module_id = None
    if module_name:
        found = repo.find_module(conn, module_name)
        if found is None:
            raise click.ClickException(f"no module called {module_name}")
        module_id = found.id

    matches = repo.find_exercises(conn, name, module_id=module_id)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise click.ClickException(f"no exercise called {name!r}{_near(conn, name)}")

    where = ", ".join(_module_name(conn, match) for match in matches)
    raise click.ClickException(f"{name!r} is in {where} — say MODULE/NAME to pick one")


def _near(conn: sqlite3.Connection, name: str) -> str:
    names = [exercise.name for exercise in repo.exercises_due(conn)]
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
    return f". Did you mean: {', '.join(close)}?" if close else ""


def _module_name(conn: sqlite3.Connection, exercise: Exercise) -> str:
    found = repo.get_module(conn, exercise.module_id)
    return found.name if found else "?"


def _tempo(exercise: Exercise) -> str:
    return format_tempo(
        parse_tempo(exercise.speed or "", target_bpm=exercise.target_bpm)
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _due_column(due: date | None) -> str:
    return due.isoformat() if due else "—"


def _when(due: date | None, today: date) -> str:
    """`3 days overdue`, `due today`, `in 30 days`."""
    if due is None:
        return "no due date"
    days = (due - today).days
    if days == 0:
        return "due today"
    if days < 0:
        return f"{-days} day{'s' if days != -1 else ''} overdue"
    return f"in {days} day{'s' if days != 1 else ''}"


def _parse_day(which: str, now: datetime | None = None) -> date:
    if which == "today":
        return practice_day_for(now or datetime.now())
    try:
        return date.fromisoformat(which)
    except ValueError:
        raise click.ClickException(f"cannot read the date {which!r}") from None


def _seconds(entry: PracticeEntry, now: datetime) -> int:
    live = now if practice_day_for(now) == practice_day_for(entry.started_at) else None
    return entry_duration(entry, now=live)
